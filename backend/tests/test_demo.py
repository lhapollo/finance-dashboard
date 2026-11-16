"""The demo data generator: it builds a believable year that the app makes sense of."""

import random
from datetime import date

import pytest

from app import config
from app.demo import _wipe, main, seed

DAY = date(2026, 11, 15)


@pytest.fixture
def seeded(db_session):
    seed(db_session, DAY, random.Random(2026))
    db_session.flush()


def test_a_year_of_transactions(client, seeded):
    page = client.get("/transactions?limit=1&order=asc").json()
    assert page["total"] > 500
    assert page["items"][0]["date"] >= "2025-11-16"


def test_transfers_and_card_payments_pair_up(client, seeded):
    transfers = client.get("/transactions?is_transfer=true&limit=500").json()["items"]
    assert len(transfers) > 40
    assert all(t["transfer_pair_id"] is not None for t in transfers)


def test_the_dashboard_has_numbers(client, seeded):
    month = client.get("/summary/month?month=2026-10").json()
    assert month["spent_cents"] > 50_000 and month["income_cents"] > 400_000
    categories = {c["category"] for c in client.get("/summary/categories?month=2026-10").json()}
    assert {"groceries", "dining", "home"} <= categories


def test_the_budget_looks_real(client, seeded):
    budget = client.get("/budget").json()
    assert budget["start_date"] == "2026-10-16"
    # Unassigned is the newest paycheck (not split yet) plus a little.
    assert 245_000 <= budget["unassigned_cents"] <= 245_000 + 25_000
    assert budget["unbucketed_spent_cents"] >= 0
    names = {b["name"] for b in budget["buckets"]}
    assert {"Rent", "Groceries", "Switch 2", "Emergency fund"} <= names

    paychecks = client.get("/paychecks").json()
    assert sum(p["split_cents"] == 0 for p in paychecks) == 1  # the newest
    assert client.get("/budget/categories").json()


def test_the_cibc_card_is_closed_and_paid_off(client, seeded):
    cibc = next(
        a
        for a in client.get("/summary/accounts?month=2026-11").json()
        if a["institution"] == "CIBC"
    )
    assert cibc["closed_on"] is not None
    assert cibc["balance_cents"] == 0


def test_refuses_a_database_that_isnt_a_demo_one(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://u:p@localhost/finance")
    monkeypatch.setattr("sys.argv", ["app.demo"])
    with pytest.raises(SystemExit, match="must end in _demo"):
        main()


def test_wiping_keeps_the_accounts(client, db_session, seeded):
    _wipe(db_session)
    assert len(client.get("/accounts").json()) == 4
    assert client.get("/transactions").json()["total"] == 0
    seed(db_session, DAY, random.Random(2026))  # and seeding again works
