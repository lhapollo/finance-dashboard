import io
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
    new = [
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
        for t, fp in zip(parsed, fps, strict=True)
        if fp not in existing
    ]
    session.add_all(new)
    session.flush()  # gives the new rows their ids, which transfer pairing needs
    detect_transfers(session)  # across all rows, since a new row may pair with an old one
    apply_renames(session)  # new rows from a merchant I've renamed get the new name
    try:
        apply_rules(session)  # also re-applies any rule edits to older rows
    except ValueError as e:  # a typo in a rules file; nothing is saved
        raise HTTPException(400, str(e)) from None
    session.commit()
    return ImportResult(inserted=len(new), skipped=len(parsed) - len(new))
