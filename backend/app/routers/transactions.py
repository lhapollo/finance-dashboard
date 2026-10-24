from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Transaction
from app.schemas import RecategorizeResult, TransactionOut, TransactionPage, TransactionUpdate
from app.services.categories import apply_rules

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("")
def list_transactions(
    session: Annotated[Session, Depends(get_session)],
    account_id: int | None = None,
    category: str | None = None,
    is_transfer: bool | None = None,
    start: date | None = None,
    end: date | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionPage:
    """Newest first. Every filter is optional; start is included, end isn't.
    `total` is how many rows match, so the table can show "page 2 of 18"."""
    filters = []
    if account_id is not None:
        filters.append(Transaction.account_id == account_id)
    if category is not None:
        filters.append(Transaction.category == category)
    if is_transfer is not None:
        filters.append(Transaction.is_transfer.is_(is_transfer))
    if start is not None:
        filters.append(Transaction.date >= start)
    if end is not None:
        filters.append(Transaction.date < end)
    if search:
        # autoescape: a search for "50%" means the text "50%", not "50 then anything".
        filters.append(
            or_(
                Transaction.description.icontains(search, autoescape=True),
                Transaction.raw_description.icontains(search, autoescape=True),
            )
        )

    total = session.scalar(select(func.count()).select_from(Transaction).where(*filters))
    rows = session.scalars(
        select(Transaction)
        .where(*filters)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return TransactionPage(items=[TransactionOut.model_validate(t) for t in rows], total=total)


@router.patch("/{transaction_id}")
def update_transaction(
    transaction_id: int,
    update: TransactionUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> TransactionOut:
    """Fix a category or transfer flag by hand. Rules and detection won't change it back."""
    t = session.get(Transaction, transaction_id)
    if t is None:
        raise HTTPException(404, f"no transaction with id {transaction_id}")

    if update.category is not None:
        t.category = update.category
        t.category_source = "manual"

    if update.is_transfer is not None:
        t.is_transfer = update.is_transfer
        t.transfer_source = "manual"
        if not update.is_transfer and t.transfer_pair_id is not None:
            # "Not a transfer" means the other side isn't one either. The other side stays
            # "auto", so detection may still pair it with something else later.
            partner = session.get(Transaction, t.transfer_pair_id)
            if partner is not None:
                partner.is_transfer = False
                partner.transfer_pair_id = None
            t.transfer_pair_id = None

    session.commit()
    return TransactionOut.model_validate(t)


@router.post("/recategorize")
def recategorize(session: Annotated[Session, Depends(get_session)]) -> RecategorizeResult:
    """Re-apply the category rule files to every row you haven't categorized by hand."""
    try:
        changed = apply_rules(session)
    except ValueError as e:  # a typo in a rules file
        raise HTTPException(400, str(e)) from None
    session.commit()
    return RecategorizeResult(changed=changed)
