import io
from collections import Counter
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.importers import CONVERTERS
from app.importers.common import ImportFormatError
from app.models import Account, Transaction
from app.schemas import ImportResult
from app.services.categories import apply_rules
from app.services.fingerprint import fingerprints
from app.services.renames import apply_renames
from app.services.transfers import detect_transfers

router = APIRouter(tags=["import"])


@router.post("/import")
def import_csv(
    file: UploadFile,
    account_id: Annotated[int, Form()],
    session: Annotated[Session, Depends(get_session)],
) -> ImportResult:
    """Upload one bank CSV for one account. Rows already imported are skipped.

    All or nothing: if any row is bad, nothing is saved and the error names the line.
    """
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, f"no account with id {account_id}")
    convert = CONVERTERS.get((account.institution, account.type))
    if convert is None:
        raise HTTPException(400, f"no CSV converter for {account.name} yet")

    try:
        text = file.file.read().decode("utf-8-sig")  # -sig: ignore the BOM Excel sometimes adds
    except UnicodeDecodeError:
        raise HTTPException(400, "file isn't UTF-8 text; is it really a CSV?") from None
    try:
        parsed = convert(io.StringIO(text, newline=""))
    except ImportFormatError as e:
        raise HTTPException(400, f"{file.filename}, {e}") from None
    if not parsed:
        raise HTTPException(400, "file has no transactions")

    fps = fingerprints(account.id, parsed)
    existing = set(
        session.scalars(select(Transaction.fingerprint).where(Transaction.fingerprint.in_(fps)))
    )
    plaid = _PlaidCopies(session, account.id)
    new = []
    for t, fp in zip(parsed, fps, strict=True):
        if fp in existing:
            continue
        if plaid.take_posted(t.date, t.amount_cents):
            continue  # Plaid already has it, worded differently enough to dodge fingerprints
        if (row := plaid.take_pending(t.date, t.amount_cents)) is not None:
            # Plaid only has it as pending. The CSV shows it posted, so that row becomes the
            # CSV row (keeping your edits); when Plaid catches up, its posted copy claims it.
            row.source = "csv"
            row.pending = False
            row.date = t.date  # the day it posted, so Plaid's posted copy matches it exactly
            row.plaid_transaction_id = None
            row.fingerprint = fp
            row.raw_description = t.raw_description
            plaid.converted += 1
            continue
        new.append(
            Transaction(
                account_id=account.id,
                date=t.date,
                description=t.description,
                cleaned_description=t.description,
                raw_description=t.raw_description,
                amount_cents=t.amount_cents,
                fingerprint=fp,
                source=t.source,
            )
        )
    session.add_all(new)
    session.flush()  # gives the new rows their ids, which transfer pairing needs
    detect_transfers(session)  # across all rows, since a new row may pair with an old one
    apply_renames(session)  # new rows from a merchant I've renamed get the new name
    try:
        apply_rules(session)  # also re-applies any rule edits to older rows
    except ValueError as e:  # a typo in a rules file; nothing is saved
        raise HTTPException(400, str(e)) from None
    session.commit()
    return ImportResult(
        inserted=len(new) + plaid.converted,
        skipped=len(parsed) - len(new) - plaid.converted,
        from_plaid=plaid.skipped,
    )


# How far a pending charge's date can be before the day it posts.
_PENDING_DAYS = timedelta(days=5)


class _PlaidCopies:
    """Transactions Plaid already brought in for this account, which a CSV row may repeat.

    Plaid sometimes falls behind a bank for days, and a CSV fills the gap. Rows Plaid has are
    matched by date and amount, one for one (two $5 coffees on a day are two rows), the same
    way a Plaid sync claims CSV rows, so either can come first without doubling up."""

    def __init__(self, session: Session, account_id: int):
        rows = session.scalars(
            select(Transaction)
            .where(Transaction.account_id == account_id, Transaction.source == "plaid")
            .order_by(Transaction.id)
        ).all()
        self.posted: Counter[tuple[date, int]] = Counter(
            (t.date, t.amount_cents) for t in rows if not t.pending
        )
        self.pending = [t for t in rows if t.pending]
        self.skipped = 0
        self.converted = 0

    def take_posted(self, day: date, amount_cents: int) -> bool:
        if self.posted[(day, amount_cents)] > 0:
            self.posted[(day, amount_cents)] -= 1
            self.skipped += 1
            return True
        return False

    def take_pending(self, day: date, amount_cents: int) -> Transaction | None:
        matches = [
            t
            for t in self.pending
            if t.amount_cents == amount_cents and day - _PENDING_DAYS <= t.date <= day
        ]
        if not matches:
            return None
        row = min(matches, key=lambda t: day - t.date)  # the closest date
        self.pending.remove(row)
        return row
