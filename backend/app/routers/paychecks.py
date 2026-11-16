"""Paychecks: where pay comes from, the usual split, and splitting each paycheck."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Account, Allocation, Bucket, IncomeSource, PaycheckRule, Transaction
from app.schemas import (
    BucketAmount,
    IncomeSourceIn,
    IncomeSourceOut,
    IncomeSourceSuggestion,
    PaycheckMark,
    PaycheckOut,
    PaycheckRuleIn,
    PaycheckRuleOut,
    PaycheckSplitSuggestion,
)
from app.services.budget import start_date
from app.services.clock import today
from app.services.format import dollars
from app.services.paychecks import detected, is_paycheck, list_paychecks, suggest_split

router = APIRouter(tags=["paychecks"])

SessionDep = Annotated[Session, Depends(get_session)]

# Before the budget starts, the paychecks list looks this far back, to check detection works.
_PREVIEW = timedelta(days=90)


# --- Income sources ------------------------------------------------------------------------


@router.get("/income-sources")
def list_income_sources(session: SessionDep) -> list[IncomeSourceOut]:
    return [
        IncomeSourceOut.model_validate(s)
        for s in session.scalars(select(IncomeSource).order_by(IncomeSource.id))
    ]


@router.post("/income-sources", status_code=status.HTTP_201_CREATED)
def create_income_source(body: IncomeSourceIn, session: SessionDep) -> IncomeSourceOut:
    _account_or_400(session, body.account_id)
    source = IncomeSource(**body.model_dump())
    session.add(source)
    session.commit()
    return IncomeSourceOut.model_validate(source)


@router.put("/income-sources/{source_id}")
def update_income_source(
    source_id: int, body: IncomeSourceIn, session: SessionDep
) -> IncomeSourceOut:
    source = session.get(IncomeSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no income source with that id")
    _account_or_400(session, body.account_id)
    for field, value in body.model_dump().items():
        setattr(source, field, value)
    session.commit()
    return IncomeSourceOut.model_validate(source)


@router.delete("/income-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income_source(source_id: int, session: SessionDep) -> None:
    source = session.get(IncomeSource, source_id)
    if source is not None:
        session.delete(source)
        session.commit()


@router.get("/income-sources/suggestions")
def suggest_income_sources(session: SessionDep) -> list[IncomeSourceSuggestion]:
    """Income deposits that came in at least twice in the last 90 days (pay that's still
    coming in, not an old job's) and no income source
    recognizes yet. Biggest total first: paychecks stand out by size, while small regular
    deposits like interest come in just as often. At most five."""
    since = today() - _PREVIEW
    rows = session.execute(
        select(
            Transaction.account_id,
            Transaction.cleaned_description,
            func.count(),
            func.max(Transaction.date),
        )
        .where(
            Transaction.date >= since,
            Transaction.amount_cents > 0,
            Transaction.is_transfer.is_(False),
            Transaction.category == "income",  # not rewards like cashback
            ~detected,
        )
        .group_by(Transaction.account_id, Transaction.cleaned_description)
        # At least twice, and $100 on average: interest and small bonuses aren't pay.
        .having(func.count() >= 2, func.avg(Transaction.amount_cents) >= 10_000)
        .order_by(func.sum(Transaction.amount_cents).desc())
        .limit(5)
    ).all()
    result = []
    for account_id, name, count, last in rows:
        amount = session.scalar(
            select(Transaction.amount_cents)
            .where(
                Transaction.account_id == account_id,
                Transaction.cleaned_description == name,
                Transaction.date == last,
                Transaction.amount_cents > 0,
            )
            .limit(1)
        )
        result.append(
            IncomeSourceSuggestion(
                account_id=account_id,
                match_text=name,
                count=count,
                last_date=last,
                last_amount_cents=amount,
            )
        )
    return result


# --- Paycheck rules ------------------------------------------------------------------------


@router.get("/paycheck-rules")
def list_rules(session: SessionDep) -> list[PaycheckRuleOut]:
    rules = session.scalars(select(PaycheckRule).order_by(PaycheckRule.priority))
    return [PaycheckRuleOut.model_validate(r) for r in rules]


@router.put("/paycheck-rules")
def replace_rules(body: list[PaycheckRuleIn], session: SessionDep) -> list[PaycheckRuleOut]:
    """Save the whole list at once, in order (fixed rules apply in their order, then percent
    rules in theirs)."""
    total_percent = sum(r.percent or 0 for r in body)
    if total_percent > 100:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"the percents add up to {total_percent}%, over 100%"
        )
    for r in body:
        bucket = session.get(Bucket, r.bucket_id)
        if bucket is None or bucket.archived:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "rules can only use open buckets")
    session.execute(delete(PaycheckRule))
    session.add_all(PaycheckRule(**r.model_dump(), priority=i) for i, r in enumerate(body))
    session.commit()
    return list_rules(session)


# --- Paychecks -----------------------------------------------------------------------------


@router.get("/paychecks")
def get_paychecks(session: SessionDep) -> list[PaycheckOut]:
    """Paychecks since the budget started, newest first. Before it starts, the last 90 days,
    to check that detection finds the right deposits."""
    budget_start = start_date(session)
    since = budget_start or today() - _PREVIEW
    return list_paychecks(session, since, budget_start)


@router.put("/paychecks/{transaction_id}/mark")
def mark_paycheck(transaction_id: int, body: PaycheckMark, session: SessionDep) -> None:
    """Say by hand that a deposit is (true) or isn't (false) a paycheck, or let detection
    decide again (null). A deposit that stops being a paycheck gives back its split."""
    t = session.get(Transaction, transaction_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no transaction with that id")
    if body.is_paycheck and (t.amount_cents <= 0 or t.is_transfer):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "only money in that isn't a transfer can be a paycheck"
        )
    t.paycheck_override = body.is_paycheck
    session.flush()
    still = session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.id == t.id, is_paycheck)
    )
    if not still:
        session.execute(
            delete(Allocation).where(
                Allocation.kind == "paycheck", Allocation.source_transaction_id == t.id
            )
        )
    session.commit()


@router.get("/paychecks/{transaction_id}/suggestion")
def get_suggestion(transaction_id: int, session: SessionDep) -> PaycheckSplitSuggestion:
    paycheck = _paycheck_or_404(session, transaction_id)
    rules = session.scalars(select(PaycheckRule)).all()
    return suggest_split(paycheck.paycheck_cents, list(rules))


@router.put("/paychecks/{transaction_id}/split")
def split_paycheck(
    transaction_id: int, body: list[BucketAmount], session: SessionDep
) -> PaycheckOut:
    """Put a paycheck into buckets, replacing any earlier split of it. Send [] to undo the
    split (the money goes back to unassigned)."""
    paycheck = _paycheck_or_404(session, transaction_id)
    if not paycheck.splittable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "this paycheck came before your budget started, so it's already part of the "
            "money you split at the start",
        )
    ids = [p.bucket_id for p in body]
    if len(ids) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "a bucket is listed twice")
    for p in body:
        bucket = session.get(Bucket, p.bucket_id)
        if bucket is None or bucket.archived:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "pick open buckets")
    total = sum(p.amount_cents for p in body)
    if total > paycheck.paycheck_cents:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"that's {dollars(total)}, but the paycheck is {dollars(paycheck.paycheck_cents)}",
        )

    session.execute(
        delete(Allocation).where(
            Allocation.kind == "paycheck", Allocation.source_transaction_id == transaction_id
        )
    )
    session.add_all(
        Allocation(
            bucket_id=p.bucket_id,
            amount_cents=p.amount_cents,
            date=paycheck.date,
            kind="paycheck",
            source_transaction_id=transaction_id,
            note=f"Paycheck {paycheck.date.isoformat()}",
        )
        for p in body
        if p.amount_cents > 0
    )
    session.commit()
    return _paycheck_or_404(session, transaction_id)


def _paycheck_or_404(session: Session, transaction_id: int) -> PaycheckOut:
    found = [
        p
        for p in list_paychecks(session, date.min, start_date(session), only_id=transaction_id)
        if p.is_paycheck
    ]
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "that transaction isn't a paycheck")
    return found[0]


def _account_or_400(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"no account with id {account_id}")
