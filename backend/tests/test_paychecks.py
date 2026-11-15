"""Paychecks: detection, marking by hand, rules, and splitting into buckets."""

from datetime import date, timedelta

import pytest

from app.models import PaycheckRule
from app.services.paychecks import suggest_split

PAY = "EFT Deposit from Rippling Canada"
START = date(2026, 10, 10)


@pytest.fixture
def rippling(client, chequing):
    response = client.post(
        "/income-sources",
        json={"name": "Internship pay", "account_id": chequing.id, "match_text": "rippling"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def buckets(client, money):
    """Rent, Food and Investing, budgeting since Oct 10 with nothing in them."""
    ids = {}
    for name in ["Rent", "Food", "Investing"]:
        body = client.post("/buckets", json={"name": name, "type": "recurring"}).json()
        ids[name] = next(b["id"] for b in body["buckets"] if b["name"] == name)
    client.post("/budget/start", json={"start_date": START.isoformat(), "opening": []})
    return ids


def paychecks(client):
    return {p["transaction_id"]: p for p in client.get("/paychecks").json()}


def rule(bucket_id, priority, amount=None, percent=None):
    kind = "fixed" if amount is not None else "percent"
    return PaycheckRule(
        bucket_id=bucket_id, kind=kind, amount_cents=amount, percent=percent, priority=priority
    )


# --- the split math ---


def test_fixed_first_then_percents_of_whats_left():
    s = suggest_split(
        300_000, [rule(1, 0, amount=150_000), rule(2, 1, percent=20), rule(3, 2, percent=10)]
    )
    assert {a.bucket_id: a.amount_cents for a in s.suggested} == {1: 150_000, 2: 30_000, 3: 15_000}
    assert s.leftover_cents == 105_000


def test_never_more_than_the_paycheck():
    s = suggest_split(
        100_000, [rule(1, 0, amount=80_000), rule(2, 1, amount=50_000), rule(3, 2, percent=50)]
    )
    assert {a.bucket_id: a.amount_cents for a in s.suggested} == {1: 80_000, 2: 20_000}
    assert s.leftover_cents == 0


def test_percents_round_down():
    s = suggest_split(1_001, [rule(1, 0, percent=50), rule(2, 1, percent=50)])
    assert [a.amount_cents for a in s.suggested] == [500, 500]
    assert s.leftover_cents == 1  # the odd cent stays unassigned


# --- detection ---


def test_detects_pay_into_the_sources_account(client, rippling, chequing, savings, add):
    pay = add(chequing, 15, 300_000, PAY, category="income")
    add(savings, 15, 300_000, PAY, category="income")  # wrong account
    add(chequing, 16, -5_000, "RIPPLING REFUND")  # money out
    add(chequing, 17, 300_000, PAY, is_transfer=True)  # a transfer
    assert list(paychecks(client)) == [pay.id]


def test_marking_by_hand_wins(client, rippling, chequing, add):
    pay = add(chequing, 15, 300_000, PAY, category="income")
    bonus = add(chequing, 16, 50_000, "EFT Deposit from Acme Bonus", category="income")
    client.put(f"/paychecks/{pay.id}/mark", json={"is_paycheck": False})
    client.put(f"/paychecks/{bonus.id}/mark", json={"is_paycheck": True})
    found = paychecks(client)
    assert found[bonus.id]["is_paycheck"] and not found[pay.id]["is_paycheck"]
    assert found[pay.id]["detected"]  # still listed, so the mark can be undone

    client.put(f"/paychecks/{pay.id}/mark", json={"is_paycheck": None})
    assert paychecks(client)[pay.id]["is_paycheck"]


def test_only_money_in_can_be_a_paycheck(client, chequing, add):
    coffee = add(chequing, 15, -500)
    response = client.put(f"/paychecks/{coffee.id}/mark", json={"is_paycheck": True})
    assert response.status_code == 400


def test_suggests_income_sources_from_repeat_deposits(client, chequing, add):
    today = date.today()
    for day in [today - timedelta(days=14), today]:
        add(chequing, day, 300_000, PAY, category="income", cleaned_description="Rippling Canada")
    add(chequing, today, 2_000, "INTEREST", category="income")  # only once
    [suggestion] = client.get("/income-sources/suggestions").json()
    assert suggestion["match_text"] == "Rippling Canada"
    assert suggestion["count"] == 2

    client.post(
        "/income-sources",
        json={"name": "Pay", "account_id": chequing.id, "match_text": "Rippling Canada"},
    )
    assert client.get("/income-sources/suggestions").json() == []


# --- rules ---


def test_rules_save_in_order_and_percents_cap_at_100(client, buckets):
    rules = [
        {"bucket_id": buckets["Rent"], "kind": "fixed", "amount_cents": 150_000},
        {"bucket_id": buckets["Investing"], "kind": "percent", "percent": 20},
    ]
    assert client.put("/paycheck-rules", json=rules).json() == [
        {"bucket_id": buckets["Rent"], "kind": "fixed", "amount_cents": 150_000, "percent": None},
        {"bucket_id": buckets["Investing"], "kind": "percent", "amount_cents": None, "percent": 20},
    ]
    rules.append({"bucket_id": buckets["Food"], "kind": "percent", "percent": 81})
    response = client.put("/paycheck-rules", json=rules)
    assert response.json()["detail"] == "the percents add up to 101%, over 100%"

    bad = [{"bucket_id": buckets["Food"], "kind": "fixed", "percent": 5}]
    assert client.put("/paycheck-rules", json=bad).status_code == 422


def test_archiving_a_bucket_drops_its_rules(client, buckets):
    rules = [{"bucket_id": buckets["Food"], "kind": "percent", "percent": 10}]
    client.put("/paycheck-rules", json=rules)
    client.patch(f"/buckets/{buckets['Food']}", json={"archived": True})
    assert client.get("/paycheck-rules").json() == []


# --- splitting ---


def test_split_a_paycheck_into_buckets(client, rippling, buckets, chequing, add):
    pay = add(chequing, 15, 300_000, PAY, category="income")
    client.put(
        "/paycheck-rules",
        json=[
            {"bucket_id": buckets["Rent"], "kind": "fixed", "amount_cents": 150_000},
            {"bucket_id": buckets["Investing"], "kind": "percent", "percent": 20},
        ],
    )
    suggestion = client.get(f"/paychecks/{pay.id}/suggestion").json()
    assert suggestion["leftover_cents"] == 120_000

    before = client.get("/budget").json()["unassigned_cents"]
    body = client.put(f"/paychecks/{pay.id}/split", json=suggestion["suggested"]).json()
    assert body["split_cents"] == 180_000
    budget = client.get("/budget").json()
    assert budget["unassigned_cents"] == before - 180_000
    assert {b["name"]: b["balance_cents"] for b in budget["buckets"]} == {
        "Rent": 150_000,
        "Food": 0,
        "Investing": 30_000,
    }

    # Splitting again replaces the earlier split instead of adding to it.
    client.put(
        f"/paychecks/{pay.id}/split", json=[{"bucket_id": buckets["Food"], "amount_cents": 1_000}]
    )
    balances = {b["name"]: b["balance_cents"] for b in client.get("/budget").json()["buckets"]}
    assert balances == {"Rent": 0, "Food": 1_000, "Investing": 0}


def test_cant_split_more_than_the_paycheck(client, rippling, buckets, chequing, add):
    pay = add(chequing, 15, 100_000, PAY, category="income")
    response = client.put(
        f"/paychecks/{pay.id}/split", json=[{"bucket_id": buckets["Rent"], "amount_cents": 100_001}]
    )
    assert response.json()["detail"] == "that's $1,000.01, but the paycheck is $1,000.00"


def test_only_the_pay_part_of_a_split_deposit_counts(client, rippling, buckets, chequing, add):
    dinner = add(chequing, 12, -4_500, "WORK DINNER", reimbursable=True)
    pay = add(chequing, 15, 134_500, PAY, category="income")
    client.put(
        f"/transactions/{pay.id}/splits",
        json=[
            {"amount_cents": 130_000, "category": "income"},
            {"amount_cents": 4_500, "category": "dining", "reimburses_id": dinner.id},
        ],
    )
    assert paychecks(client)[pay.id]["paycheck_cents"] == 130_000


def test_paychecks_before_the_start_cant_be_split(client, rippling, buckets, chequing, add):
    pay = add(chequing, 5, 300_000, PAY, category="income")  # Oct 5, before Oct 10
    client.post("/budget/start", json={"start_date": "2026-10-01", "opening": []})
    assert paychecks(client)[pay.id]["splittable"]
    client.post("/budget/start", json={"start_date": START.isoformat(), "opening": []})
    response = client.put(f"/paychecks/{pay.id}/split", json=[])
    assert response.status_code == 400
    assert "before your budget started" in response.json()["detail"]
    assert pay.id not in paychecks(client)  # the list starts at the budget start


def test_unmarking_gives_back_the_split(client, rippling, buckets, chequing, add):
    pay = add(chequing, 15, 300_000, PAY, category="income")
    client.put(
        f"/paychecks/{pay.id}/split", json=[{"bucket_id": buckets["Rent"], "amount_cents": 50_000}]
    )
    client.put(f"/paychecks/{pay.id}/mark", json={"is_paycheck": False})
    assert {b["name"]: b["balance_cents"] for b in client.get("/budget").json()["buckets"]}[
        "Rent"
    ] == 0
