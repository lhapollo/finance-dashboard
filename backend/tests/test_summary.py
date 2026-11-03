from datetime import date

import pytest

from app.services.summaries import add_months


@pytest.fixture
def october(card, add):
    """A small made-up October 2026, plus a September and a 2025 row to compare against."""
    add(card, 3, -4618, "LOBLAWS", category="groceries")
    add(card, 9, -2000, "T&T", category="groceries")
    add(card, 12, -1500, "HERO TEA", category="dining")
    add(card, 14, 2260, "PIZZA PLACE REFUND", category="dining")  # money in
    add(card, 17, 81240, "PRE-AUTHORIZED PAYMENT", is_transfer=True)  # never counts
    add(card, 31, -500, "LAST DAY", category="dining")
    add(card, date(2026, 11, 1), -9999, "NEXT MONTH", category="dining")
    add(card, date(2026, 9, 30), -5000, "SEPTEMBER", category="dining")
    add(card, date(2025, 6, 1), -1000, "LAST YEAR", category="shopping")


@pytest.mark.parametrize(
    "d, months, expected",
    [
        (date(2026, 10, 15), 1, date(2026, 11, 1)),
        (date(2026, 12, 1), 1, date(2027, 1, 1)),
        (date(2026, 1, 31), -1, date(2025, 12, 1)),
        (date(2026, 10, 1), -11, date(2025, 11, 1)),
    ],
)
def test_add_months(d, months, expected):
    assert add_months(d, months) == expected


def test_month_summary(client, october):
    body = client.get("/summary/month", params={"month": "2026-10"}).json()

    spent = 4618 + 2000 + 1500 + 500
    assert body == {
        "month": "2026-10-01",
        "spent_cents": spent,
        "income_cents": 2260,  # the refund; the card payment is a transfer
        "net_cents": 2260 - spent,
        "previous_spent_cents": 5000,
        "change_pct": round((spent - 5000) / 5000 * 100, 1),
    }


def test_month_with_no_previous_spending(client, october):
    body = client.get("/summary/month", params={"month": "2025-06"}).json()

    assert body["spent_cents"] == 1000
    assert body["change_pct"] is None


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "oct", "2026-00"])
def test_month_summary_rejects_bad_month(client, month):
    assert client.get("/summary/month", params={"month": month}).status_code == 422


def test_spending_by_category(client, october):
    body = client.get(
        "/summary/categories", params={"start": "2026-10-01", "end": "2026-11-01"}
    ).json()

    assert body == [
        {"category": "groceries", "total_cents": 6618},
        {"category": "dining", "total_cents": 2000},  # money out only, refund not subtracted
    ]


def test_spending_by_category_rejects_backwards_range(client):
    response = client.get(
        "/summary/categories", params={"start": "2026-10-02", "end": "2026-10-01"}
    )

    assert response.status_code == 400


def test_spending_over_time_by_month(client, october):
    body = client.get("/summary/over-time", params={"month": "2026-10", "months": 2}).json()

    assert body == [
        {"period": "2026-09-01", "category": "dining", "total_cents": 5000},
        {"period": "2026-10-01", "category": "groceries", "total_cents": 6618},
        {"period": "2026-10-01", "category": "dining", "total_cents": 2000},
    ]


def test_spending_over_time_by_year(client, october):
    body = client.get("/summary/over-time", params={"group_by": "year", "month": "2026-12"}).json()

    assert body == [
        {"period": "2025-01-01", "category": "shopping", "total_cents": 1000},
        {"period": "2026-01-01", "category": "dining", "total_cents": 2000 + 5000 + 9999},
        {"period": "2026-01-01", "category": "groceries", "total_cents": 6618},
    ]


def test_list_accounts(client):
    body = client.get("/accounts").json()

    assert [(a["name"], a["institution"], a["type"]) for a in body] == [
        ("CIBC Credit Card", "CIBC", "credit"),
        ("Tangerine Chequing", "Tangerine", "chequing"),
        ("Tangerine Mastercard", "Tangerine", "credit"),
    ]


def test_list_transactions_newest_first(client, october):
    body = client.get("/transactions", params={"limit": 3}).json()

    assert body["total"] == 9
    assert [t["raw_description"] for t in body["items"]] == [
        "NEXT MONTH",
        "LAST DAY",
        "PRE-AUTHORIZED PAYMENT",
    ]


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"category": "groceries"}, ["T&T", "LOBLAWS"]),
        ({"start": "2026-10-12", "end": "2026-10-17"}, ["PIZZA PLACE REFUND", "HERO TEA"]),
        ({"is_transfer": True}, ["PRE-AUTHORIZED PAYMENT"]),
        ({"search": "loblaws"}, ["LOBLAWS"]),
        ({"search": "%"}, []),  # a literal %, not a wildcard
        ({"account_id": 999}, []),
    ],
)
def test_list_transactions_filters(client, october, params, expected):
    body = client.get("/transactions", params=params).json()

    assert [t["raw_description"] for t in body["items"]] == expected
    assert body["total"] == len(expected)


def test_list_transactions_paging(client, october):
    first = client.get("/transactions", params={"limit": 4}).json()
    second = client.get("/transactions", params={"limit": 4, "offset": 4}).json()

    ids = [t["id"] for t in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 8
    assert second["total"] == 9
