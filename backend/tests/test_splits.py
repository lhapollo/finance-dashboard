"""Split transactions: one transaction counted as several parts, e.g. a paycheck that
includes a work reimbursement, or a Costco trip that's part groceries, part household."""

from datetime import date

import pytest

from app.services.transfers import detect_transfers


@pytest.fixture
def work_dinner(card, add):
    """$45 team dinner on October 10 that work pays back on the next paycheck."""
    return add(card, 10, -4500, "PIZZA PLACE", category="dining")


@pytest.fixture
def paycheck(chequing, add):
    """$1,345 on October 15: $1,300 of pay plus the $45 for the dinner."""
    return add(chequing, 15, 134500, "EFT DEPOSIT FROM RIPPLING CANADA", category="income")


@pytest.fixture
def costco(card, add):
    return add(card, 20, -12000, "COSTCO WHOLESALE", category="groceries")


def split(client, t, *parts):
    return client.put(f"/transactions/{t.id}/splits", json=list(parts))


def part(cents, category, reimburses=None):
    body = {"amount_cents": cents, "category": category}
    if reimburses is not None:
        body["reimburses_id"] = reimburses.id
    return body


def month(client, m="2026-10"):
    return client.get("/summary/month", params={"month": m}).json()


def categories(client):
    body = client.get(
        "/summary/categories", params={"start": "2026-10-01", "end": "2026-11-01"}
    ).json()
    return {c["category"]: c["total_cents"] for c in body}


def test_paycheck_with_a_reimbursement(client, paycheck, work_dinner):
    """The design doc's example: only $1,300 is income, and the dinner is fully paid back."""
    response = split(client, paycheck, part(130000, "income"), part(4500, "income", work_dinner))

    assert response.status_code == 200
    assert [(s["amount_cents"], s["counted_category"]) for s in response.json()["splits"]] == [
        (130000, "income"),
        (4500, "dining"),  # counts against the dinner
    ]
    october = month(client)
    assert (october["income_cents"], october["spent_cents"]) == (130000, 0)
    dinner = client.get(f"/transactions/{work_dinner.id}").json()
    assert dinner["reimbursed_cents"] == 4500
    assert dinner["reimbursement_ids"] == [paycheck.id]


def test_reimbursable_dinner_paid_back_by_a_paycheck_part(client, paycheck, work_dinner):
    client.patch(f"/transactions/{work_dinner.id}", json={"reimbursable": True})
    split(client, paycheck, part(130000, "income"), part(4500, "income", work_dinner))

    assert month(client)["income_cents"] == 130000  # the $45 isn't income either
    dinner = client.get(f"/transactions/{work_dinner.id}").json()
    assert dinner["reimbursement_status"] == "received"
    owed = client.get("/summary/reimbursements").json()
    assert owed == {"waiting_cents": 0, "count": 0}


def test_purchase_split_across_categories(client, costco):
    split(client, costco, part(-9000, "groceries"), part(-3000, "household"))

    assert categories(client) == {"groceries": 9000, "household": 3000}
    assert month(client)["spent_cents"] == 12000
    over_time = client.get("/summary/over-time", params={"month": "2026-10", "months": 1})
    assert {r["category"]: r["total_cents"] for r in over_time.json()} == {
        "groceries": 9000,
        "household": 3000,
    }


def test_category_filter_finds_split_parts(client, costco, card, add):
    add(card, 21, -500, "HOME DEPOT", category="household")
    split(client, costco, part(-9000, "groceries"), part(-3000, "household"))

    household = client.get("/transactions", params={"category": "household"}).json()
    groceries = client.get("/transactions", params={"category": "groceries"}).json()

    assert len(household["items"]) == 2
    assert [t["id"] for t in groceries["items"]] == [costco.id]


def test_resplitting_replaces_and_empty_removes(client, costco):
    split(client, costco, part(-9000, "groceries"), part(-3000, "household"))
    response = split(client, costco, part(-6000, "groceries"), part(-6000, "household"))

    assert [s["amount_cents"] for s in response.json()["splits"]] == [-6000, -6000]
    assert categories(client) == {"groceries": 6000, "household": 6000}

    assert split(client, costco).json()["splits"] == []
    assert categories(client) == {"groceries": 12000}


def test_moving_a_payback_part_between_purchases(client, paycheck, work_dinner, card, add):
    """Re-saving a split doesn't count its own old parts against the purchase."""
    split(client, paycheck, part(130000, "income"), part(4500, "income", work_dinner))

    again = split(client, paycheck, part(130000, "income"), part(4500, "income", work_dinner))

    assert again.status_code == 200
    assert client.get(f"/transactions/{work_dinner.id}").json()["reimbursed_cents"] == 4500


@pytest.mark.parametrize(
    "parts, message",
    [
        ([part(-12000, "groceries")], "at least 2 parts"),
        ([part(-9000, "groceries"), part(-2000, "household")], "add up"),
        ([part(-13000, "groceries"), part(1000, "household")], "every part must be money out"),
        ([part(-12000, "groceries"), part(0, "household")], "every part must be money out"),
    ],
)
def test_bad_splits(client, costco, parts, message):
    response = split(client, costco, *parts)

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_payback_part_cant_be_more_than_the_purchase(client, paycheck, work_dinner):
    response = split(client, paycheck, part(129000, "income"), part(5500, "income", work_dinner))

    assert response.status_code == 400
    assert "more than the purchase cost" in response.json()["detail"]


def test_money_out_parts_cant_pay_anything_back(client, costco, work_dinner):
    response = split(client, costco, part(-9000, "groceries"), part(-3000, "dining", work_dinner))

    assert response.status_code == 400
    assert "only money in" in response.json()["detail"]


def test_what_cant_be_split(client, card, chequing, add, work_dinner):
    transfer = add(card, 3, 50000, "PAYMENT THANK YOU", is_transfer=True)
    reimbursable = add(card, 4, -2000, "LUNCH", reimbursable=True)
    payback = add(chequing, 11, 2000, "E-TRANSFER", reimburses_id=work_dinner.id)

    for t, message in [
        (transfer, "a transfer can't be split"),
        (reimbursable, "reimbursable"),
        (payback, "pays back a purchase"),
        (work_dinner, "has paybacks"),
    ]:
        half = t.amount_cents // 2
        response = split(client, t, part(half, "x"), part(t.amount_cents - half, "x"))
        assert response.status_code == 400, t.raw_description
        assert message in response.json()["detail"]


def test_split_transaction_cant_become_a_transfer_or_reimbursable(client, costco):
    split(client, costco, part(-9000, "groceries"), part(-3000, "household"))

    for body in ({"is_transfer": True}, {"reimbursable": True}):
        response = client.patch(f"/transactions/{costco.id}", json=body)
        assert response.status_code == 400
        assert "split" in response.json()["detail"]


def test_split_purchase_cant_be_paid_back(client, costco, chequing, add):
    split(client, costco, part(-9000, "groceries"), part(-3000, "household"))
    payback = add(chequing, 22, 3000, "E-TRANSFER")

    response = client.patch(f"/transactions/{payback.id}", json={"reimburses_id": costco.id})

    assert response.status_code == 400
    assert "split purchase" in response.json()["detail"]


def test_transfer_detection_skips_split_transactions(db_session, client, chequing, savings, add):
    """A split $500 withdrawal and $500 arriving in savings the next day stay as they are."""
    out = add(chequing, 5, -50000, "SOMETHING", category="shopping")
    arrived = add(savings, 6, 50000)
    split(client, out, part(-30000, "shopping"), part(-20000, "home"))

    detect_transfers(db_session)

    assert not out.is_transfer and not arrived.is_transfer


def test_splits_keep_the_parent_date(client, chequing, add, work_dinner):
    """A payback part dates by its purchase, like a whole payback would."""
    november_pay = add(chequing, date(2026, 11, 1), 134500, "EFT DEPOSIT", category="income")
    split(client, november_pay, part(130000, "income"), part(4500, "income", work_dinner))

    assert month(client, "2026-10")["spent_cents"] == 0  # dinner paid back in its own month
    assert month(client, "2026-11")["income_cents"] == 130000
