from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models import Transaction
from app.schemas import RecategorizeResult, TransactionOut, TransactionPage, TransactionUpdate
from app.services.categories import apply_rules
from app.services.renames import apply_renames, rename_merchant

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Loads what TransactionOut's payback fields need in two extra queries per page, instead of
# two per row.
_WITH_PAYBACKS = (selectinload(Transaction.reimburses), selectinload(Transaction.reimbursements))


@router.get("")
def list_transactions(
    session: Annotated[Session, Depends(get_session)],
    account_id: int | None = None,
    category: str | None = None,
    is_transfer: bool | None = None,
    start: date | None = None,
    end: date | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    money: Literal["in", "out"] | None = None,
    reimbursable: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Literal["desc", "asc"] = "desc",
) -> TransactionPage:
    """Newest first (order=desc), or oldest first (order=asc). Every filter is optional;
    start is included, end isn't. `total` is how many rows match, so the table can show
    "page 2 of 18".

    category matches the category a row counts toward, so a payback linked to a dinner shows
    up under dining. money=out is only money out, money=in only money in."""
    filters = []
    if account_id is not None:
        filters.append(Transaction.account_id == account_id)
    if category is not None:
        in_category = select(Transaction.id).where(Transaction.category == category)
        filters.append(
            or_(
                and_(Transaction.reimburses_id.is_(None), Transaction.category == category),
                Transaction.reimburses_id.in_(in_category.scalar_subquery()),
            )
        )
    if money == "in":
        filters.append(Transaction.amount_cents > 0)
    elif money == "out":
        filters.append(Transaction.amount_cents < 0)
    if is_transfer is not None:
        filters.append(Transaction.is_transfer.is_(is_transfer))
    if reimbursable is not None:
        filters.append(Transaction.reimbursable.is_(reimbursable))
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
        .options(*_WITH_PAYBACKS)
        .where(*filters)
        # id breaks ties within a day, so paging never skips or repeats a row.
        .order_by(
            *(
                (Transaction.date.desc(), Transaction.id.desc())
                if order == "desc"
                else (Transaction.date.asc(), Transaction.id.asc())
            )
        )
        .limit(limit)
        .offset(offset)
    )
    return TransactionPage(items=[TransactionOut.model_validate(t) for t in rows], total=total)


@router.get("/{transaction_id}")
def get_transaction(
    transaction_id: int, session: Annotated[Session, Depends(get_session)]
) -> TransactionOut:
    t = session.get(Transaction, transaction_id)
    if t is None:
        raise HTTPException(404, f"no transaction with id {transaction_id}")
    return TransactionOut.model_validate(t)


@router.patch("/{transaction_id}")
def update_transaction(
    transaction_id: int,
    update: TransactionUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> TransactionOut:
    """Fix a name, category or transfer flag by hand, link a payback to its purchase, or mark
    a purchase as reimbursable. Rules and detection won't change it back."""
    t = session.get(Transaction, transaction_id)
    if t is None:
        raise HTTPException(404, f"no transaction with id {transaction_id}")

    # model_fields_set tells "description: null" (undo the rename) apart from not sending it.
    if "description" in update.model_fields_set:
        if update.rename_all:
            # This row follows the rule too, even if it was renamed by hand before.
            t.description_source = "auto"
            rename_merchant(
                session, t.cleaned_description, update.description or t.cleaned_description
            )
        elif update.description is None:
            t.description_source = "auto"  # back to the rule's name, or the converter's
            apply_renames(session)
        else:
            t.description = update.description
            t.description_source = "manual"

    if update.category is not None:
        t.category = update.category
        t.category_source = "manual"

    if "reimburses_id" in update.model_fields_set:
        # Setting the relationship (not just the id) keeps the purchase's list of paybacks
        # up to date too.
        t.reimburses = (
            None
            if update.reimburses_id is None
            else _payback_target(session, t, update.reimburses_id)
        )

    if update.reimbursable is not None:
        if update.reimbursable and t.amount_cents > 0:
            raise HTTPException(400, "only money out can be reimbursable")
        if update.reimbursable and t.is_transfer:
            raise HTTPException(400, "a transfer can't be reimbursable")
        t.reimbursable = update.reimbursable

    if update.is_transfer is not None:
        if update.is_transfer and (t.reimburses is not None or t.reimbursements):
            raise HTTPException(
                400, "a payback or a paid-back purchase can't be a transfer; unlink it first"
            )
        if update.is_transfer and t.reimbursable:
            raise HTTPException(400, "a reimbursable purchase can't be a transfer")
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


def _payback_target(session: Session, payback: Transaction, purchase_id: int) -> Transaction:
    """The purchase `payback` can be linked to. Raises a 400 saying why if it can't."""
    purchase = session.get(Transaction, purchase_id)
    if purchase is None:
        raise HTTPException(400, f"no transaction with id {purchase_id}")
    if payback.amount_cents < 0:
        raise HTTPException(400, "only money in can pay back a purchase")
    if payback.is_transfer:
        raise HTTPException(400, "a transfer can't pay back a purchase")
    if purchase.amount_cents > 0:
        raise HTTPException(400, "only money out can be paid back")
    if purchase.is_transfer:
        raise HTTPException(400, "a transfer can't be paid back")
    already = sum(r.amount_cents for r in purchase.reimbursements if r.id != payback.id)
    if already + payback.amount_cents > -purchase.amount_cents:
        raise HTTPException(400, "that's more than the purchase cost, counting earlier paybacks")
    return purchase


@router.post("/recategorize")
def recategorize(session: Annotated[Session, Depends(get_session)]) -> RecategorizeResult:
    """Re-apply the category rule files to every row you haven't categorized by hand."""
    try:
        changed = apply_rules(session)
    except ValueError as e:  # a typo in a rules file
        raise HTTPException(400, str(e)) from None
    session.commit()
    return RecategorizeResult(changed=changed)
