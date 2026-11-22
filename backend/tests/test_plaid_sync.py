"""Syncing transactions from Plaid, against a fake Plaid with scripted pages of changes."""

from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app import config
from app.importers.plaid import convert_plaid
from app.main import app
from app.models import Account, PlaidItem, Transaction
from app.plaid import PlaidError, get_plaid
from app.routers import plaid as plaid_router
from app.services.secrets import encrypt_token

TOKEN = "access-production-abc"

# Plaid's view of a Tangerine login: its three accounts, with balances as Plaid reports them
# (a credit card's positive balance is money owed).
PLAID_ACCOUNTS = [
    {"account_id": "pa-card", "name": "Mastercard", "mask": "4536", "type": "credit",
     "subtype": "credit card", "balances": {"current": 691.06}},
    {"account_id": "pa-chq", "name": "Chequing", "mask": "9003", "type": "depository",
     "subtype": "checking", "balances": {"current": 2500.1}},
    {"account_id": "pa-sav", "name": "Savings", "mask": "9041", "type": "depository",
     "subtype": "savings", "balances": {"current": 8000.0}},
]  # fmt: skip


def plaid_txn(tid, account, day, amount, desc="SOMETHING", **extra):
    """A transaction as Plaid sends it: positive amount = money OUT."""
    return {
        "transaction_id": tid,
        "account_id": account,
        "date": day,
        "authorized_date": extra.pop("authorized_date", day),
        "amount": amount,
        "name": desc.title(),
        "original_description": desc,
        "pending": False,
        "pending_transaction_id": None,
        **extra,
    }


class FakePlaid:
    environment = "production"

    def __init__(self):
        self.pages: dict[str, dict] = {}  # cursor sent -> page returned
        self.calls: list[tuple[str, dict]] = []
        self.fail_with: PlaidError | None = None
        self.fail_once: PlaidError | None = None
        # Plaid's last successful check of the bank, as /item/get reports it.
        self.last_successful_update: str | None = "2026-11-18T21:45:40.88Z"

    def page(self, cursor, next_cursor, added=(), modified=(), removed=(), has_more=False):
        self.pages[cursor] = {
            "added": list(added),
            "modified": list(modified),
            "removed": [{"transaction_id": r} for r in removed],
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    def post(self, path, body):
        self.calls.append((path, body))
        if self.fail_with:
            raise self.fail_with
        if path == "/link/token/create":
            return {"link_token": "link-update"}
        if path == "/accounts/get":
            return {"accounts": PLAID_ACCOUNTS}
        if path == "/item/get":
            update = {"last_successful_update": self.last_successful_update}
            return {"item": {"item_id": "item-1"}, "status": {"transactions": update}}
        if path == "/transactions/sync":
            assert body["access_token"] == TOKEN
            if self.fail_once:
                error, self.fail_once = self.fail_once, None
                raise error
            return self.pages[body["cursor"]]
        raise AssertionError(f"unexpected call to {path}")


@pytest.fixture(autouse=True)
def production(monkeypatch):
    monkeypatch.setattr(config, "PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "PLAID_ENV", "production")


@pytest.fixture
def fake(monkeypatch):
    fake = FakePlaid()
    app.dependency_overrides[get_plaid] = lambda: fake
    monkeypatch.setattr(plaid_router, "get_plaid", lambda: fake)
    return fake


@pytest.fixture
def card(db_session):
    return db_session.scalar(select(Account).where(Account.name == "Tangerine Mastercard"))


@pytest.fixture
def item(db_session):
    item = PlaidItem(
        item_id="item-1",
        institution_name="Tangerine - Personal",
        environment="production",
        access_token=encrypt_token(TOKEN),
    )
    db_session.add(item)
    db_session.flush()
    return item


@pytest.fixture
def linked(client, fake, item, card, chequing, savings):
    """All three accounts linked, as the Accounts page would do it."""
    links = [
        {"plaid_account_id": "pa-card", "account_id": card.id},
        {"plaid_account_id": "pa-chq", "account_id": chequing.id},
        {"plaid_account_id": "pa-sav", "account_id": savings.id},
    ]
    response = client.put(f"/plaid/items/{item.id}/accounts", json={"links": links})
    assert response.status_code == 200, response.text
    return item


def sync(client, force=True):
    response = client.post(f"/plaid/sync?force={str(force).lower()}")
    assert response.status_code == 200, response.text
    return response.json()


def rows(db_session, account):
    return db_session.scalars(
        select(Transaction).where(Transaction.account_id == account.id).order_by(Transaction.date)
    ).all()


# --- the converter ---


def test_convert_flips_the_sign_and_keeps_exact_cents(chequing):
    t = convert_plaid(plaid_txn("t1", "pa-chq", "2026-11-10", 12.1), chequing).transaction
    assert t.amount_cents == -1210  # Plaid's positive = money out
    t = convert_plaid(plaid_txn("t2", "pa-chq", "2026-11-10", -500.0), chequing).transaction
    assert t.amount_cents == 50000


def test_cards_use_the_purchase_date_banks_the_posted_date(card, chequing):
    raw = plaid_txn("t1", "pa-card", "2026-11-12", 5, authorized_date="2026-11-10")
    assert convert_plaid(raw, card).transaction.date == date(2026, 11, 10)
    assert convert_plaid(raw, chequing).transaction.date == date(2026, 11, 12)


def test_convert_uses_the_banks_own_wording_and_cleanup(chequing):
    raw = plaid_txn("t1", "pa-chq", "2026-11-10", 5, "Interac - Purchase - SHEIN  TORONTO, ON")
    p = convert_plaid(raw, chequing)
    assert p.transaction.raw_description == "Interac - Purchase - SHEIN TORONTO, ON"
    assert p.transaction.description == "Shein"  # as Tangerine's CSV converter cleans it
    assert p.plaid_transaction_id == "t1"


def test_convert_drops_plaids_posted_date_suffix(chequing):
    desc = "Visa Debit - Purchase - Amazon.ca*1Z88158D3 866-216-1072, CA Posted :08 Nov 2026"
    t = convert_plaid(plaid_txn("t1", "pa-chq", "2026-11-09", 5, desc), chequing).transaction
    assert t.raw_description == "Visa Debit - Purchase - Amazon.ca*1Z88158D3 866-216-1072, CA"
    assert t.description == "Amazon.ca"


# --- linking accounts ---


def test_suggests_the_matching_account_of_each_kind(client, fake, item, card, chequing, savings):
    accounts = client.get(f"/plaid/items/{item.id}/accounts").json()
    assert {a["plaid_account_id"]: a["suggested_account_id"] for a in accounts} == {
        "pa-card": card.id,
        "pa-chq": chequing.id,
        "pa-sav": savings.id,
    }
    assert all(a["account_id"] is None for a in accounts)


def test_linking_sets_the_cutoff_to_the_last_csv_day(client, fake, item, chequing, add, db_session):
    add(chequing, 20, -500)
    add(chequing, 28, -700)
    item.cursor = "old"
    links = [{"plaid_account_id": "pa-chq", "account_id": chequing.id}]
    response = client.put(f"/plaid/items/{item.id}/accounts", json={"links": links})
    assert response.status_code == 200
    assert chequing.plaid_account_id == "pa-chq"
    assert chequing.csv_cutoff_date == date(2026, 10, 28)
    assert item.cursor is None  # next sync starts over, to get the new account's history


def test_linking_rejects_unknown_or_doubled_accounts(client, fake, item, chequing):
    bad = [{"plaid_account_id": "not-in-this-bank", "account_id": chequing.id}]
    assert client.put(f"/plaid/items/{item.id}/accounts", json={"links": bad}).status_code == 400
    doubled = [
        {"plaid_account_id": "pa-chq", "account_id": chequing.id},
        {"plaid_account_id": "pa-sav", "account_id": chequing.id},
    ]
    response = client.put(f"/plaid/items/{item.id}/accounts", json={"links": doubled})
    assert response.status_code == 400


# --- syncing ---


def test_plaid_claims_csv_rows_and_adds_only_whats_missing(
    client, fake, item, card, add, db_session
):
    csv_row = add(card, 30, -2243, "HARVEST GREEN TORONTO O")
    links = [{"plaid_account_id": "pa-card", "account_id": card.id}]
    client.put(f"/plaid/items/{item.id}/accounts", json={"links": links})
    fake.page(
        "",
        "c1",
        added=[
            # Same purchase as the CSV row, worded a little differently: claimed, not added.
            plaid_txn("p1", "pa-card", "2026-11-02", 22.43, "HARVEST GREEN TORONTO ON",
                      authorized_date="2026-10-30"),
            # The same amount again that day: the CSV missed it, so it's added.
            plaid_txn("p2", "pa-card", "2026-11-02", 22.43, "HARVEST GREEN TORONTO ON",
                      authorized_date="2026-10-30"),
        ],
    )  # fmt: skip
    [result] = sync(client)
    assert (result["matched"], result["added"]) == (1, 1)

    saved = rows(db_session, card)
    assert len(saved) == 2
    assert csv_row.plaid_transaction_id == "p1"
    assert csv_row.raw_description == "HARVEST GREEN TORONTO O"  # the CSV's facts stay
    new = next(t for t in saved if t.source == "plaid")
    assert (new.date, new.amount_cents, new.plaid_transaction_id) == (
        date(2026, 10, 30),
        -2243,
        "p2",
    )


def test_new_rows_get_categories_and_transfers(client, fake, linked, chequing, db_session):
    fake.page(
        "",
        "c1",
        added=[
            plaid_txn("p1", "pa-chq", "2026-11-10", 30, "Interac - Purchase - SHEIN TORONTO, ON"),
            plaid_txn(
                "p2", "pa-chq", "2026-11-11", 100, "Internet Withdrawal to Tangerine Savings"
            ),
        ],
    )
    sync(client)
    shein, transfer = rows(db_session, chequing)
    assert shein.category == "shopping"
    assert transfer.is_transfer


def test_the_cursor_is_saved_and_the_next_sync_continues_from_it(
    client, fake, linked, chequing, db_session
):
    fake.page("", "c1", added=[plaid_txn("p1", "pa-chq", "2026-11-10", 5)], has_more=True)
    fake.page("c1", "c2", added=[plaid_txn("p2", "pa-chq", "2026-11-11", 6)])
    assert sync(client)[0]["added"] == 2
    assert linked.cursor == "c2"
    assert linked.last_synced_at is not None

    fake.page("c2", "c3", added=[plaid_txn("p3", "pa-chq", "2026-11-12", 7)])
    assert sync(client)[0]["added"] == 1
    assert len(rows(db_session, chequing)) == 3


def test_sync_saves_when_plaid_last_reached_the_bank(client, fake, linked):
    # Our sync succeeds, but Plaid's own last check of the bank is days old: the page shows
    # this so you know to reconnect.
    fake.page("", "c1")
    sync(client)
    assert linked.status == "ok"
    assert linked.bank_updated_at == datetime(2026, 11, 18, 21, 45, 40, 880000, tzinfo=UTC)
    bank = client.get("/plaid/items").json()[0]
    assert bank["bank_updated_at"].startswith("2026-11-18T21:45:40.88")

    # Before Plaid's first successful check there's no date yet.
    fake.last_successful_update = None
    fake.page("c1", "c2")
    sync(client)
    assert linked.bank_updated_at is None


def test_a_pending_charge_that_posts_keeps_your_edits(client, fake, linked, card, db_session):
    fake.page(
        "",
        "c1",
        added=[plaid_txn("pend", "pa-card", "2026-11-10", 40, "BAR RAVAL", pending=True)],
    )
    sync(client)
    [row] = rows(db_session, card)
    assert row.pending
    row.category, row.category_source = "restaurants", "manual"

    # It posts with the tip added: Plaid removes the pending one and adds the posted one.
    posted = plaid_txn(
        "post", "pa-card", "2026-11-12", 48, "BAR RAVAL", pending_transaction_id="pend",
        authorized_date="2026-11-10",
    )  # fmt: skip
    fake.page("c1", "c2", added=[posted], removed=["pend"])
    result = sync(client)[0]
    assert (result["added"], result["removed"]) == (0, 0)

    [row] = rows(db_session, card)
    assert (row.pending, row.amount_cents, row.plaid_transaction_id) == (False, -4800, "post")
    assert row.category == "restaurants"


def test_modified_and_removed(client, fake, linked, chequing, add, db_session):
    csv_row = add(chequing, 15, -900, "SOMETHING")
    fake.page(
        "",
        "c1",
        added=[
            plaid_txn("p1", "pa-chq", "2026-11-10", 5),
            plaid_txn("p2", "pa-chq", "2026-11-11", 6),
            plaid_txn("p3", "pa-chq", "2026-10-15", 9),  # claims the CSV row
        ],
    )
    sync(client)
    assert csv_row.plaid_transaction_id == "p3"

    fake.page(
        "c1",
        "c2",
        modified=[plaid_txn("p1", "pa-chq", "2026-11-10", 5.5)],
        removed=["p2", "p3"],
    )
    result = sync(client)[0]
    assert (result["updated"], result["removed"]) == (1, 1)
    remaining = rows(db_session, chequing)
    assert [t.amount_cents for t in remaining] == [-900, -550]
    assert csv_row in remaining  # CSV rows are never deleted by Plaid
    assert csv_row.plaid_transaction_id is None


def test_removing_one_side_of_a_transfer_unpairs_the_other(
    client, fake, linked, chequing, savings, db_session
):
    fake.page(
        "",
        "c1",
        added=[
            plaid_txn("out", "pa-chq", "2026-11-10", 250, "EFT TO SOMEONE"),
            plaid_txn("in", "pa-sav", "2026-11-11", -250, "DEPOSIT"),
        ],
    )
    sync(client)
    [deposit] = rows(db_session, savings)
    assert deposit.is_transfer

    fake.page("c1", "c2", removed=["out"])
    sync(client)
    assert (deposit.is_transfer, deposit.transfer_pair_id) == (False, None)


def test_unlinked_accounts_are_skipped_and_named(client, fake, item, chequing, db_session):
    links = [{"plaid_account_id": "pa-chq", "account_id": chequing.id}]
    client.put(f"/plaid/items/{item.id}/accounts", json={"links": links})
    fake.page(
        "",
        "c1",
        added=[
            plaid_txn("p1", "pa-chq", "2026-11-10", 5),
            plaid_txn("p2", "pa-sav", "2026-11-10", 5),
        ],
    )
    result = sync(client)[0]
    assert result["added"] == 1
    assert result["unlinked_accounts"] == ["pa-sav"]


def test_a_plaid_error_is_recorded_and_changes_nothing(client, fake, linked, chequing, db_session):
    linked.cursor = "c1"
    fake.fail_once = PlaidError("ITEM_LOGIN_REQUIRED", "log in again")
    result = sync(client)[0]
    assert result["error"] == "log in again"
    assert linked.status == "ITEM_LOGIN_REQUIRED"
    assert linked.cursor == "c1"
    assert rows(db_session, chequing) == []


def test_data_changing_mid_sync_restarts_from_the_original_cursor(
    client, fake, linked, chequing, db_session
):
    fake.page("", "c1", added=[plaid_txn("p1", "pa-chq", "2026-11-10", 5)])
    fake.fail_once = PlaidError("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION", "retry")
    result = sync(client)[0]
    assert (result["error"], result["added"]) == (None, 1)


def test_without_force_only_stale_banks_sync(client, fake, linked, db_session):
    linked.last_synced_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.flush()
    assert sync(client, force=False) == []
    linked.last_synced_at = datetime.now(UTC) - timedelta(hours=7)
    fake.page("", "c1")
    assert len(sync(client, force=False)) == 1


def test_sync_with_nothing_connected_needs_no_keys(client, monkeypatch):
    monkeypatch.setattr(config, "PLAID_CLIENT_ID", "")
    assert sync(client, force=False) == []


# --- CSVs after linking ---


def import_csv(client, account, *lines):
    csv = "Date,Transaction,Name,Memo,Amount\n" + "".join(f"{line}\n" for line in lines)
    response = client.post(
        "/import", data={"account_id": account.id}, files={"file": ("x.csv", csv, "text/csv")}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_csv_fills_in_what_plaid_is_missing(client, fake, linked, chequing, db_session):
    # Plaid stopped reaching the bank after the coffee.
    fake.page("", "c1", added=[plaid_txn("p1", "pa-chq", "2026-11-04", 4.5, "COFFEE")])
    sync(client)

    result = import_csv(
        client,
        chequing,
        "11/4/2026,DEBIT,Coffee,,-4.50",  # Plaid has it: skipped
        "11/9/2026,DEBIT,Lunch,,-12.00",  # Plaid doesn't: imported
        "11/9/2026,DEBIT,Lunch,,-12.00",  # a second, identical lunch is its own row
    )
    assert result == {"inserted": 2, "skipped": 1, "from_plaid": 1}

    # Plaid catches up: its copies claim the CSV rows instead of doubling up.
    fake.page(
        "c1",
        "c2",
        added=[
            plaid_txn("p2", "pa-chq", "2026-11-09", 12, "LUNCH"),
            plaid_txn("p3", "pa-chq", "2026-11-09", 12, "LUNCH"),
        ],
    )
    result = sync(client)[0]
    assert (result["added"], result["matched"]) == (0, 2)
    assert sorted(t.plaid_transaction_id for t in rows(db_session, chequing)) == ["p1", "p2", "p3"]
    assert len(rows(db_session, chequing)) == 3


def test_a_csv_row_turns_plaids_pending_copy_into_a_posted_one(
    client, fake, linked, chequing, db_session
):
    pending = plaid_txn("pend", "pa-chq", "2026-11-07", 30, "BAR RAVAL", pending=True)
    fake.page("", "c1", added=[pending])
    sync(client)
    [row] = rows(db_session, chequing)
    row.category, row.category_source = "restaurants", "manual"

    # The CSV has it posted two days later: the same row, now posted, keeping the edit.
    result = import_csv(client, chequing, "11/9/2026,DEBIT,Bar Raval,,-30.00")
    assert result == {"inserted": 1, "skipped": 0, "from_plaid": 0}
    [row] = rows(db_session, chequing)
    assert (row.pending, row.source, row.date) == (False, "csv", date(2026, 11, 9))
    assert row.category == "restaurants"
    assert import_csv(client, chequing, "11/9/2026,DEBIT,Bar Raval,,-30.00")["inserted"] == 0

    # Plaid posts it: its posted copy claims the row, and its pending one is gone.
    posted = plaid_txn(
        "post", "pa-chq", "2026-11-09", 30, "BAR RAVAL", pending_transaction_id="pend"
    )
    fake.page("c1", "c2", added=[posted], removed=["pend"])
    result = sync(client)[0]
    assert (result["added"], result["matched"]) == (0, 1)
    [row] = rows(db_session, chequing)
    assert (row.plaid_transaction_id, row.category) == ("post", "restaurants")


def test_plaid_posting_drops_its_pending_copy_when_a_csv_row_has_it(
    client, fake, linked, chequing, add, db_session
):
    # Pending at Plaid, and (too far apart to be matched on import) already in from a CSV.
    fake.page("", "c1", added=[plaid_txn("pend", "pa-chq", "2026-11-01", 30, pending=True)])
    sync(client)
    add(chequing, date(2026, 11, 9), -3000)

    posted = plaid_txn("post", "pa-chq", "2026-11-09", 30, pending_transaction_id="pend")
    fake.page("c1", "c2", added=[posted], removed=["pend"])
    result = sync(client)[0]
    assert (result["added"], result["matched"], result["removed"]) == (0, 1, 1)
    [row] = rows(db_session, chequing)
    assert (row.source, row.plaid_transaction_id, row.pending) == ("csv", "post", False)


def test_balances_count_csv_rows_plaid_hasnt_seen(client, fake, linked, chequing, db_session):
    from app.services.summaries import balance_summary

    fake.page("", "c1")
    sync(client)  # chequing's balance from Plaid: $2,500.10
    before = balance_summary(db_session).cash_cents
    import_csv(client, chequing, "11/9/2026,DEBIT,Lunch,,-12.00")
    assert balance_summary(db_session).cash_cents == before - 1200

    # Once Plaid has it, the bank's balance is trusted again: it includes the lunch, so
    # counting the row on top would take it off twice.
    PLAID_ACCOUNTS[1]["balances"]["current"] -= 12
    try:
        fake.page("c1", "c2", added=[plaid_txn("p1", "pa-chq", "2026-11-09", 12, "LUNCH")])
        sync(client)
    finally:
        PLAID_ACCOUNTS[1]["balances"]["current"] += 12
    assert balance_summary(db_session).cash_cents == before - 1200


def test_disconnecting_returns_accounts_to_csv(client, fake, linked, chequing, db_session):
    fake.fail_with = PlaidError("ITEM_NOT_FOUND", "gone")  # already gone at Plaid's end
    assert client.delete(f"/plaid/items/{linked.id}").status_code == 204
    assert (chequing.plaid_account_id, chequing.csv_cutoff_date) == (None, None)


def test_reconnecting_uses_update_mode(client, fake, item):
    response = client.post(f"/plaid/link-token?item_id={item.id}")
    assert response.json() == {"link_token": "link-update"}
    path, body = fake.calls[-1]
    assert body["access_token"] == TOKEN  # the existing login, not a new one
    assert "products" not in body


# --- balances ---


def test_sync_saves_balances_signed_like_transactions(
    client, fake, linked, card, chequing, savings
):
    fake.page("", "c1")
    sync(client)
    assert (card.balance_cents, chequing.balance_cents, savings.balance_cents) == (
        -69106,
        250010,
        800000,
    )
    assert chequing.balance_updated_at is not None


def test_available_money_is_cash_minus_card_debt(client, fake, linked, db_session):
    fake.page("", "c1")
    sync(client)
    body = client.get("/summary/balances").json()
    assert (body["cash_cents"], body["owed_cents"], body["available_cents"]) == (
        1050010,
        69106,
        980904,
    )
    assert body["missing"] == ["CIBC Credit Card"]  # not on Plaid, so no balance

    cibc = db_session.scalar(select(Account).where(Account.name == "CIBC Credit Card"))
    client.patch(f"/accounts/{cibc.id}", json={"closed_on": "2026-11-20"})
    assert client.get("/summary/balances").json()["missing"] == []
