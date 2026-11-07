"""Refunds and paybacks: money in that lowers spending instead of counting as income."""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import Account
from app.services.transfers import detect_transfers


@pytest.fixture
def chequing(db_session):
    """The Tangerine chequing account that a migration seeds."""
    return db_session.scalar(select(Account).where(Account.name == "Tangerine Chequing"))


@pytest.fixture
def dinner(card, add):
    """$80 dinner on October 28 that a friend owes half of."""
    return add(card, 28, -8000, "PIZZA PLACE", category="dining")


@pytest.fixture
def payback(chequing, add):
    """The friend's $40 e-transfer, arriving in November."""
    return add(
        chequing, date(2026, 11, 3), 4000, "INTERAC E-TRANSFER FROM SAM", category="e-transfers"
    )


def link(client, payback_id, purchase_id):
    return client.patch(f"/transactions/{payback_id}", json={"reimburses_id": purchase_id})


def month(client, m):
    return client.get("/summary/month", params={"month": m}).json()


def categories(client, start, end):
    body = client.get("/summary/categories", params={"start": start, "end": end}).json()
    return {c["category"]: c["total_cents"] for c in body}


def test_unlinked_payback_lowers_its_own_category(client, dinner, payback):
    november = month(client, "2026-11")

    assert november["spent_cents"] == -4000
    assert november["income_cents"] == 0
    assert categories(client, "2026-11-01", "2026-12-01") == {"e-transfers": -4000}


def test_linked_payback_counts_in_the_purchase_month_and_category(client, dinner, payback):
    assert link(client, payback.id, dinner.id).status_code == 200

    assert month(client, "2026-10")["spent_cents"] == 4000  # my half of dinner
    assert categories(client, "2026-10-01", "2026-11-01") == {"dining": 4000}
    assert month(client, "2026-11")["spent_cents"] == 0
    assert categories(client, "2026-11-01", "2026-12-01") == {}


def test_linked_payback_follows_the_purchase_category(client, dinner, payback):
    link(client, payback.id, dinner.id)
    client.patch(f"/transactions/{dinner.id}", json={"category": "entertainment"})

    assert categories(client, "2026-10-01", "2026-11-01") == {"entertainment": 4000}


def test_linked_payback_in_spending_over_time(client, dinner, payback):
    link(client, payback.id, dinner.id)

    body = client.get("/summary/over-time", params={"month": "2026-11", "months": 2}).json()

    assert body == [{"period": "2026-10-01", "category": "dining", "total_cents": 4000}]


def test_income_categories_count_as_income(client, card, chequing, add):
    add(chequing, 1, 250000, "RIPPLING PAYROLL", category="income")
    add(card, 2, 1500, "CASHBACK/REMISE EN ARGENT", category="rewards")
    add(card, 3, -6000, "UNIQLO", category="shopping")

    body = month(client, "2026-10")

    assert body["income_cents"] == 251500
    assert body["spent_cents"] == 6000
    assert categories(client, "2026-10-01", "2026-11-01") == {"shopping": 6000}


def test_fully_refunded_category_is_left_out(client, card, add):
    add(card, 3, -6000, "UNIQLO", category="shopping")
    add(card, 9, 6000, "UNIQLO", category="shopping")
    add(card, 9, -1200, "HERO TEA", category="dining")

    assert categories(client, "2026-10-01", "2026-11-01") == {"dining": 1200}
    assert month(client, "2026-10")["spent_cents"] == 1200


def test_link_shows_on_both_sides(client, dinner, payback):
    body = link(client, payback.id, dinner.id).json()

    assert body["reimburses_id"] == dinner.id
    assert body["counted_category"] == "dining"
    assert body["category"] == "e-transfers"  # its own category is kept, for if it's unlinked

    purchase = client.get(f"/transactions/{dinner.id}").json()
    assert purchase["reimbursement_ids"] == [payback.id]
    assert purchase["reimbursed_cents"] == 4000


def test_several_paybacks_for_one_purchase(client, chequing, add, dinner, payback):
    other = add(chequing, date(2026, 11, 4), 2000, "E-TRANSFER FROM ALEX", category="e-transfers")
    link(client, payback.id, dinner.id)
    link(client, other.id, dinner.id)

    purchase = client.get(f"/transactions/{dinner.id}").json()
    assert purchase["reimbursement_ids"] == [payback.id, other.id]
    assert purchase["reimbursed_cents"] == 6000
    assert month(client, "2026-10")["spent_cents"] == 2000


def test_unlink(client, dinner, payback):
    link(client, payback.id, dinner.id)

    body = link(client, payback.id, None).json()

    assert body["reimburses_id"] is None
    assert body["counted_category"] == "e-transfers"
    assert client.get(f"/transactions/{dinner.id}").json()["reimbursement_ids"] == []
    assert month(client, "2026-10")["spent_cents"] == 8000


def test_relinking_to_another_purchase_moves_it(client, card, add, dinner, payback):
    lunch = add(card, 29, -4000, "HERO TEA", category="dining")
    link(client, payback.id, dinner.id)

    assert link(client, payback.id, lunch.id).status_code == 200

    assert client.get(f"/transactions/{dinner.id}").json()["reimbursement_ids"] == []
    assert client.get(f"/transactions/{lunch.id}").json()["reimbursed_cents"] == 4000


def test_relinking_the_same_payback_doesnt_count_it_twice(client, card, add, chequing):
    purchase = add(card, 1, -4000, "CONCERT", category="entertainment")
    full = add(chequing, 2, 4000, "E-TRANSFER", category="e-transfers")
    link(client, full.id, purchase.id)

    assert link(client, full.id, purchase.id).status_code == 200


@pytest.mark.parametrize(
    "case, message",
    [
        ("payback_is_money_out", "only money in"),
        ("purchase_is_money_in", "only money out"),
        ("payback_is_transfer", "a transfer can't pay back"),
        ("purchase_is_transfer", "a transfer can't be paid back"),
        ("too_much", "more than the purchase cost"),
        ("unknown_purchase", "no transaction with id"),
    ],
)
def test_link_rejected(client, card, chequing, add, case, message):
    purchase = add(card, 1, -3000, "DINNER", category="dining")
    payback = add(chequing, 2, 1000, "E-TRANSFER", category="e-transfers")
    target = purchase.id
    if case == "payback_is_money_out":
        payback = add(chequing, 2, -1000, "E-TRANSFER")
    elif case == "purchase_is_money_in":
        target = add(card, 1, 3000, "REFUND").id
    elif case == "payback_is_transfer":
        payback.is_transfer = True
    elif case == "purchase_is_transfer":
        purchase.is_transfer = True
    elif case == "too_much":
        link(client, add(chequing, 2, 2500, "E-TRANSFER").id, purchase.id)  # 2500 of 3000
    elif case == "unknown_purchase":
        target = 999999

    response = link(client, payback.id, target)

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_linked_rows_cant_be_marked_transfers(client, dinner, payback):
    link(client, payback.id, dinner.id)

    for t in (payback, dinner):
        response = client.patch(f"/transactions/{t.id}", json={"is_transfer": True})
        assert response.status_code == 400


def test_category_filter_includes_linked_paybacks(client, dinner, payback):
    link(client, payback.id, dinner.id)

    dining = client.get("/transactions", params={"category": "dining"}).json()
    e_transfers = client.get("/transactions", params={"category": "e-transfers"}).json()

    assert [t["id"] for t in dining["items"]] == [payback.id, dinner.id]
    assert e_transfers["items"] == []


@pytest.mark.parametrize("money, expected", [("in", "payback"), ("out", "dinner")])
def test_money_filter(client, dinner, payback, money, expected):
    body = client.get("/transactions", params={"money": money}).json()

    assert [t["id"] for t in body["items"]] == [{"payback": payback, "dinner": dinner}[expected].id]


def test_transfer_detection_leaves_linked_paybacks_alone(
    db_session, client, chequing, savings, add, card
):
    purchase = add(card, 1, -8000, "DINNER", category="dining")
    add(chequing, 3, -4000, "SOMETHING ELSE")  # same amount, close date: looks like a transfer
    friend = add(savings, 4, 4000, "E-TRANSFER", category="e-transfers")
    link(client, friend.id, purchase.id)

    detect_transfers(db_session)

    assert not friend.is_transfer
