from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models import Bucket, Transaction, TransactionSplit
from app.schemas import (
    RecategorizeResult,
    SplitIn,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
)
from app.services.budget import start_date
from app.services.categories import apply_rules
from app.services.renames import apply_renames, rename_merchant
from app.services.summaries import transactions_in_bucket

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Loads what TransactionOut's payback and split fields need in a few extra queries per page,
# instead of a few per row.
_WITH_PAYBACKS = (
    selectinload(Transaction.reimburses),
    selectinload(Transaction.reimbursements),
    selectinload(Transaction.split_paybacks),
    selectinload(Transaction.splits).selectinload(TransactionSplit.reimburses),
)


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
    bucket_id: int | None = None,
    unbucketed: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Literal["desc", "asc"] = "desc",
) -> TransactionPage:
    """Newest first (order=desc), or oldest first (order=asc). Every filter is optional;
    start is included, end isn't. `total` is how many rows match, so the table can show
    "page 2 of 18".

    category matches the category a row counts toward, so a payback linked to a dinner shows
    up under dining, and a split transaction shows up under each of its parts' categories.
    money=out is only money out, money=in only money in.

    bucket_id: spending that comes out of that bucket since the budget started (refunds and
    paybacks into it too); unbucketed=true: spending since then that no bucket covers."""
    filters = []
    if bucket_id is not None or unbucketed:
        budget_start = start_date(session)
        if budget_start is None:
            filters.append(False)  # no budget yet, so nothing comes out of a bucket
        else:
            filters.append(Transaction.id.in_(transactions_in_bucket(bucket_id, budget_start)))
    if account_id is not None:
        filters.append(Transaction.account_id == account_id)
    if category is not None:
        in_category = select(Transaction.id).where(Transaction.category == category)
        purchases = in_category.scalar_subquery()
        filters.append(
            or_(
                and_(
                    Transaction.reimburses_id.is_(None),
                    ~Transaction.splits.any(),
                    Transaction.category == category,
                ),
                Transaction.reimburses_id.in_(purchases),
                Transaction.splits.any(
                    or_(
                        and_(
                            TransactionSplit.reimburses_id.is_(None),
                            TransactionSplit.category == category,
                        ),
                        TransactionSplit.reimburses_id.in_(purchases),
                    )
                ),
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

    if update.bucket_auto:
        t.bucket_id, t.bucket_assigned_by = None, None
    elif "bucket_id" in update.model_fields_set:
        if t.reimburses is not None:
            raise HTTPException(
                400, "a payback goes back into its purchase's bucket; change it on the purchase"
            )
        if update.bucket_id is not None:
            bucket = session.get(Bucket, update.bucket_id)
            if bucket is None or bucket.archived:
                raise HTTPException(400, "pick an open bucket")
        t.bucket_id, t.bucket_assigned_by = update.bucket_id, "manual"

    if t.splits and (
        update.is_transfer
        or update.reimbursable
        or ("reimburses_id" in update.model_fields_set and update.reimburses_id is not None)
    ):
        raise HTTPException(
            400,
            "a split transaction can't be a transfer, reimbursable or a payback; "
            "use its parts, or remove the split first",
        )

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
    _check_purchase(purchase, payback.amount_cents, already_linked=payback.id)
    return purchase


def _check_purchase(purchase: Transaction, cents: int, already_linked: int) -> None:
    """Raises a 400 if `cents` more paid back would be more than `purchase` cost, or if the
    purchase is split. Paybacks from transaction `already_linked` (whole, or its parts) are
    being replaced, so they don't count."""
    if purchase.splits:
        raise HTTPException(400, "a split purchase can't be paid back; remove the split first")
    already = sum(r.amount_cents for r in purchase.reimbursements if r.id != already_linked)
    already += sum(
        s.amount_cents for s in purchase.split_paybacks if s.transaction_id != already_linked
    )
    if already + cents > -purchase.amount_cents:
        raise HTTPException(400, "that's more than the purchase cost, counting earlier paybacks")


@router.put("/{transaction_id}/splits")
def set_splits(
    transaction_id: int,
    parts: list[SplitIn],
    session: Annotated[Session, Depends(get_session)],
) -> TransactionOut:
    """Split a transaction into parts, replacing any earlier split. Send [] to remove the
    split. The parts must add up to the transaction's amount, each with the same sign.

    Example: a $1,345 paycheck as [{"amount_cents": 130000, "category": "income"},
    {"amount_cents": 4500, "category": "income", "reimburses_id": <the work dinner>}]."""
    t = session.get(Transaction, transaction_id)
    if t is None:
        raise HTTPException(404, f"no transaction with id {transaction_id}")

    if parts:
        if t.is_transfer:
            raise HTTPException(400, "a transfer can't be split")
        if t.reimbursable:
            raise HTTPException(400, "a reimbursable purchase can't be split; unmark it first")
        if t.reimburses is not None:
            raise HTTPException(400, "this pays back a purchase; unlink it first")
        if t.reimbursements or t.split_paybacks:
            raise HTTPException(400, "this purchase has paybacks; unlink them first")
        if len(parts) < 2:
            raise HTTPException(400, "a split needs at least 2 parts")
        if any(p.amount_cents == 0 or (p.amount_cents > 0) != (t.amount_cents > 0) for p in parts):
            raise HTTPException(
                400, "every part must be money " + ("in" if t.amount_cents > 0 else "out")
            )
        if sum(p.amount_cents for p in parts) != t.amount_cents:
            raise HTTPException(400, "the parts must add up to the transaction's amount")

    # Paybacks: check each purchase, counting every part of this split that pays it back.
    per_purchase: dict[int, int] = {}
    for p in parts:
        if p.reimburses_id is not None:
            per_purchase[p.reimburses_id] = per_purchase.get(p.reimburses_id, 0) + p.amount_cents
    for purchase_id, cents in per_purchase.items():
        purchase = session.get(Transaction, purchase_id)
        if purchase is None:
            raise HTTPException(400, f"no transaction with id {purchase_id}")
        if t.amount_cents < 0:
            raise HTTPException(400, "only money in can pay back a purchase")
        if purchase.id == t.id or purchase.amount_cents > 0 or purchase.is_transfer:
            raise HTTPException(400, "only money out that isn't a transfer can be paid back")
        _check_purchase(purchase, cents, already_linked=t.id)

    t.splits = [
        TransactionSplit(
            amount_cents=p.amount_cents, category=p.category, reimburses_id=p.reimburses_id
        )
        for p in parts
    ]
    session.commit()
    # Purchases already loaded still list the old parts as paybacks; reload everything.
    session.expire_all()
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
