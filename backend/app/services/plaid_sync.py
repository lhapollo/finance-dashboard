"""Syncing transactions from Plaid.

Plaid's /transactions/sync works like a bookmark (the "cursor"): you send the cursor from last
time and get back only what changed since then, in three lists:
- added: new transactions.
- modified: ones whose details changed, e.g. a pending charge whose amount changed.
- removed: ones that disappeared, e.g. a pending charge the bank cancelled.
With no cursor, "added" is all the history Plaid has.

The cursor is saved only after every change is applied, in the same database commit. If
anything fails halfway, nothing is saved and the next sync starts from the old cursor again.

Overlap with CSV imports: Plaid's history goes back further than the day an account was
linked, so it repeats transactions already imported from CSVs, worded differently enough that
fingerprints can't spot them. Instead, a Plaid transaction "claims" a CSV row on the same
account with the same date and amount, one to one. On real Tangerine data every overlapping
transaction found its CSV row this way, and the only Plaid one left over was a purchase the
last CSV download was too early to include, which then gets added.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers.plaid import PlaidTransaction, convert_plaid
from app.models import Account, PlaidItem, Transaction
from app.plaid import PlaidClient, PlaidError
from app.services.categories import apply_rules
from app.services.renames import apply_renames
from app.services.secrets import TokenKeyError, decrypt_token
from app.services.transfers import detect_transfers

# Opening the dashboard syncs banks not synced for this long. Plaid itself only checks your
# bank a few times a day, so syncing more often than this rarely finds anything new.
STALE_AFTER = timedelta(hours=6)

# Plaid asks to restart from the original cursor if data changed while paging; give up after
# this many tries and let the next sync try again.
_MAX_ATTEMPTS = 3


@dataclass
class SyncResult:
    item_id: int
    institution_name: str
    added: int = 0  # new transactions saved
    matched: int = 0  # Plaid transactions that were already imported from a CSV
    updated: int = 0  # changed by Plaid (e.g. a pending charge that posted)
    removed: int = 0
    # Plaid accounts not linked to one of yours: their transactions were skipped. Linking
    # one later starts the next sync over from the beginning, so nothing is lost.
    unlinked_accounts: list[str] = field(default_factory=list)
    error: str | None = None


def plaid_fingerprint(plaid_transaction_id: str) -> str:
    """Plaid rows are identified by Plaid's id; this just fills the required fingerprint."""
    return hashlib.sha256(f"plaid|{plaid_transaction_id}".encode()).hexdigest()


def is_stale(item: PlaidItem, now: datetime) -> bool:
    return item.last_synced_at is None or now - item.last_synced_at >= STALE_AFTER


def sync_item(session: Session, plaid: PlaidClient, item_id: int) -> SyncResult:
    """Fetch everything new for one bank login and apply it. Commits on success; on failure,
    records the error on the login (e.g. ITEM_LOGIN_REQUIRED) and changes nothing else."""
    # Lock the login's row until commit. A second sync of the same login (a "Sync now" click
    # while the dashboard's sync runs) skips it instead of applying the same changes twice.
    item = session.scalar(
        select(PlaidItem).where(PlaidItem.id == item_id).with_for_update(skip_locked=True)
    )
    if item is None:
        return SyncResult(item_id, "", error="already syncing")
    result = SyncResult(item.id, item.institution_name)

    try:
        token = decrypt_token(item.access_token)
        added, modified, removed, cursor = _fetch_changes(plaid, token, item.cursor)
        balances = plaid.post("/accounts/get", {"access_token": token})["accounts"]
        bank_updated_at = _bank_updated_at(plaid.post("/item/get", {"access_token": token}))
    except (PlaidError, TokenKeyError) as e:
        item.status = e.code if isinstance(e, PlaidError) else "TOKEN_KEY_CHANGED"
        session.commit()
        result.error = str(e)
        return result

    accounts = {a.plaid_account_id: a for a in item.accounts}
    result.unlinked_accounts = sorted({t["account_id"] for t in added + modified} - accounts.keys())
    _Applier(session, item, accounts, result).apply(added, modified, removed)

    now = datetime.now(UTC)
    for pa in balances:
        if (account := accounts.get(pa["account_id"])) is not None:
            account.balance_cents = _balance_cents(pa, account)
            account.balance_updated_at = now

    item.cursor = cursor
    item.last_synced_at = now
    item.bank_updated_at = bank_updated_at
    item.status = "ok"
    session.flush()
    detect_transfers(session)
    apply_renames(session)
    apply_rules(session)
    session.commit()
    return result


def _bank_updated_at(item_info: dict[str, Any]) -> datetime | None:
    """When Plaid last got transactions from the bank, from Plaid's /item/get. Missing until
    Plaid's first successful check."""
    status = item_info.get("status") or {}
    when = (status.get("transactions") or {}).get("last_successful_update")
    return datetime.fromisoformat(when) if when else None


def _balance_cents(plaid_account: dict[str, Any], account: Account) -> int | None:
    """Plaid's current balance, signed like our transactions. Plaid reports what a credit
    card owes as a positive number; to us money owed is negative."""
    current = plaid_account["balances"].get("current")
    if current is None:
        return None
    cents = int((Decimal(str(current)) * 100).quantize(Decimal(1)))
    return -cents if account.type == "credit" else cents


def _fetch_changes(
    plaid: PlaidClient, token: str, cursor: str | None
) -> tuple[list[dict], list[dict], list[dict], str]:
    """All pages of changes since `cursor`. Large updates come in pages (`has_more`)."""
    for attempt in range(_MAX_ATTEMPTS):
        added: list[dict] = []
        modified: list[dict] = []
        removed: list[dict] = []
        next_cursor = cursor or ""
        try:
            while True:
                page = plaid.post(
                    "/transactions/sync",
                    {
                        "access_token": token,
                        "cursor": next_cursor,
                        "count": 500,
                        # The bank's own wording, which our rules are written against.
                        "options": {"include_original_description": True},
                    },
                )
                added += page["added"]
                modified += page["modified"]
                removed += page["removed"]
                next_cursor = page["next_cursor"]
                if not page["has_more"]:
                    return added, modified, removed, next_cursor
        except PlaidError as e:
            last_try = attempt == _MAX_ATTEMPTS - 1
            if e.code != "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" or last_try:
                raise
    raise AssertionError("unreachable")


class _Applier:
    """Applies one sync's changes to the database."""

    def __init__(self, session, item, accounts: dict[str, Account], result: SyncResult):
        self.session = session
        self.accounts = accounts
        self.result = result
        account_ids = [a.id for a in accounts.values()]
        rows = session.scalars(
            select(Transaction).where(Transaction.account_id.in_(account_ids))
        ).all()
        # Rows Plaid already knows, by Plaid's id.
        self.by_plaid_id = {t.plaid_transaction_id: t for t in rows if t.plaid_transaction_id}
        # CSV rows no Plaid transaction has claimed yet, by (account, date, amount).
        self.unclaimed: dict[tuple, list[Transaction]] = defaultdict(list)
        for t in sorted(rows, key=lambda t: t.id):
            if t.source == "csv" and t.plaid_transaction_id is None:
                self.unclaimed[(t.account_id, t.date, t.amount_cents)].append(t)

    def apply(self, added: list[dict], modified: list[dict], removed: list[dict]) -> None:
        for raw in added:
            if (converted := self._convert(raw)) is not None:
                self._add(*converted)
        for raw in modified:
            if (converted := self._convert(raw)) is not None:
                p, account = converted
                row = self.by_plaid_id.get(p.plaid_transaction_id)
                if row is None:
                    self._add(p, account)
                elif row.source == "plaid":
                    self._update(row, p)
        for raw in removed:
            self._remove(raw["transaction_id"])

    def _convert(self, raw: dict[str, Any]) -> tuple[PlaidTransaction, Account] | None:
        account = self.accounts.get(raw["account_id"])
        if account is None:
            return None  # an account you haven't linked (see SyncResult.unlinked_accounts)
        try:
            return convert_plaid(raw, account), account
        except ValidationError:
            return None  # e.g. a $0.00 card verification charge: not a transaction to us

    def _add(self, p: PlaidTransaction, account: Account) -> None:
        t = p.transaction

        # Seen before (a repeat sync from scratch, after linking another account).
        if (row := self.by_plaid_id.get(p.plaid_transaction_id)) is not None:
            if row.source == "plaid":
                self._update(row, p)
            return

        # Already imported from a CSV (before linking, or while Plaid was behind): Plaid
        # claims that row instead of adding a copy. If Plaid also had it as pending, that
        # pending copy is now a duplicate.
        if not p.pending and (candidates := self.unclaimed[(account.id, t.date, t.amount_cents)]):
            row = candidates.pop(0)
            row.plaid_transaction_id = p.plaid_transaction_id
            self.by_plaid_id[p.plaid_transaction_id] = row
            self.result.matched += 1
            if p.pending_transaction_id:
                # Keep a note written on the pending copy before it's deleted.
                pending = self.by_plaid_id.get(p.pending_transaction_id)
                if pending is not None and pending.note and not row.note:
                    row.note = pending.note
                self._remove(p.pending_transaction_id)
            return

        # A posted transaction replacing the pending one: update that row in place, so any
        # category or name you gave the pending one carries over.
        if p.pending_transaction_id and (
            row := self.by_plaid_id.pop(p.pending_transaction_id, None)
        ):
            row.plaid_transaction_id = p.plaid_transaction_id
            row.fingerprint = plaid_fingerprint(p.plaid_transaction_id)
            self.by_plaid_id[p.plaid_transaction_id] = row
            self._update(row, p)
            return

        row = Transaction(
            account=account,
            date=t.date,
            description=t.description,
            cleaned_description=t.description,
            raw_description=t.raw_description,
            amount_cents=t.amount_cents,
            fingerprint=plaid_fingerprint(p.plaid_transaction_id),
            source="plaid",
            plaid_transaction_id=p.plaid_transaction_id,
            pending=p.pending,
        )
        self.session.add(row)
        self.by_plaid_id[p.plaid_transaction_id] = row
        self.result.added += 1

    def _update(self, row: Transaction, p: PlaidTransaction) -> None:
        """Plaid changed a transaction it owns. Your own edits (name, category, transfer)
        stay; only the bank's facts change."""
        t = p.transaction
        if row.amount_cents != t.amount_cents and row.transfer_pair_id is not None:
            _unpair(self.session, row)  # the old pairing was for a different amount
        row.date = t.date
        row.amount_cents = t.amount_cents
        row.raw_description = t.raw_description
        row.cleaned_description = t.description
        if row.description_source == "auto":
            row.description = t.description
        row.pending = p.pending
        self.result.updated += 1

    def _remove(self, plaid_transaction_id: str) -> None:
        row = self.by_plaid_id.pop(plaid_transaction_id, None)
        if row is None:
            return
        if row.source == "csv":
            # Plaid dropped its copy, but the CSV row is a fact from the bank's own export.
            row.plaid_transaction_id = None
            return
        if row.transfer_pair_id is not None:
            _unpair(self.session, row)
        self.session.delete(row)
        self.result.removed += 1


def _unpair(session: Session, row: Transaction) -> None:
    """Undo an automatic transfer pairing, so detection can pair both sides afresh."""
    partner = session.get(Transaction, row.transfer_pair_id)
    for t in (row, partner):
        if t is None:
            continue
        t.transfer_pair_id = None
        if t.transfer_source == "auto":
            t.is_transfer = False
    session.flush()
