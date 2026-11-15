"""Paychecks: recognizing them, and suggesting how to split one into buckets.

Whether a deposit is a paycheck is worked out when asked, not stored: it's money in (not a
transfer) to an income source's account, whose description contains the source's text. Only
my own "yes, it is" / "no, it isn't" is saved (Transaction.paycheck_override), and it always
wins over detection.

Splitting follows the paycheck rules: fixed amounts first, in order, then percents of what's
left after them. The suggestion never adds up to more than the paycheck; any rounding or
leftover stays unassigned.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Allocation, IncomeSource, PaycheckRule, Transaction
from app.schemas import BucketAmount, PaycheckOut, PaycheckSplitSuggestion
from app.services.summaries import INCOME_CATEGORIES


def _contains(text, part):
    """Case-insensitive "text contains part", without LIKE's wildcard characters."""
    return func.strpos(func.lower(text), func.lower(part)) > 0


_detected = exists().where(
    IncomeSource.active.is_(True),
    IncomeSource.account_id == Transaction.account_id,
    or_(
        _contains(Transaction.raw_description, IncomeSource.match_text),
        _contains(Transaction.cleaned_description, IncomeSource.match_text),
    ),
)

# Detection only looks at money in that isn't a transfer; a mark by hand always wins.
detected = and_(Transaction.amount_cents > 0, Transaction.is_transfer.is_(False), _detected)
is_paycheck = or_(
    Transaction.paycheck_override.is_(True),
    and_(Transaction.paycheck_override.is_(None), detected),
)


def paycheck_cents(t: Transaction) -> int:
    """The pay in a deposit: all of it, or, if it's split, its income parts (not a payback
    part, which is a reimbursement for a purchase)."""
    if not t.splits:
        return t.amount_cents
    return sum(
        p.amount_cents
        for p in t.splits
        if p.reimburses_id is None and p.category in INCOME_CATEGORIES
    )


def list_paychecks(
    session: Session, since: date, budget_start: date | None, only_id: int | None = None
) -> list[PaycheckOut]:
    """Paychecks dated `since` or later, newest first. Paychecks I unmarked are included
    (is_paycheck false) only when detection would have found them, so they can be undone."""
    rows = session.execute(
        select(Transaction, detected.label("detected"))
        .options(selectinload(Transaction.splits))
        .where(
            Transaction.date >= since,
            or_(is_paycheck, and_(Transaction.paycheck_override.is_(False), detected)),
            *([Transaction.id == only_id] if only_id is not None else []),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    ).all()
    split = _split_by_paycheck(session, [t.id for t, _ in rows])
    out = []
    for t, was_detected in rows:
        parts = split.get(t.id, [])
        paycheck = t.paycheck_override if t.paycheck_override is not None else was_detected
        out.append(
            PaycheckOut(
                transaction_id=t.id,
                date=t.date,
                description=t.description,
                account_id=t.account_id,
                deposit_cents=t.amount_cents,
                paycheck_cents=paycheck_cents(t),
                detected=was_detected,
                override=t.paycheck_override,
                is_paycheck=paycheck,
                splittable=paycheck and budget_start is not None and t.date >= budget_start,
                split=parts,
                split_cents=sum(p.amount_cents for p in parts),
            )
        )
    return out


def _split_by_paycheck(session: Session, ids: list[int]) -> dict[int, list[BucketAmount]]:
    rows = session.execute(
        select(Allocation.source_transaction_id, Allocation.bucket_id, Allocation.amount_cents)
        .where(Allocation.kind == "paycheck", Allocation.source_transaction_id.in_(ids))
        .order_by(Allocation.id)
    )
    result: dict[int, list[BucketAmount]] = defaultdict(list)
    for txn, bucket, cents in rows:
        result[txn].append(BucketAmount(bucket_id=bucket, amount_cents=cents))
    return result


def suggest_split(paycheck: int, rules: list[PaycheckRule]) -> PaycheckSplitSuggestion:
    """Fixed amounts first (in order, each capped at what's left), then each percent of what
    the fixed amounts left. Rounds down, so it never assigns more than the paycheck."""
    amounts: dict[int, int] = defaultdict(int)
    remaining = paycheck
    ordered = sorted(rules, key=lambda r: r.priority)
    for r in (r for r in ordered if r.kind == "fixed"):
        take = min(r.amount_cents, remaining)
        amounts[r.bucket_id] += take
        remaining -= take
    after_fixed = remaining
    for r in (r for r in ordered if r.kind == "percent"):
        take = min(after_fixed * r.percent // 100, remaining)
        amounts[r.bucket_id] += take
        remaining -= take
    return PaycheckSplitSuggestion(
        paycheck_cents=paycheck,
        suggested=[BucketAmount(bucket_id=b, amount_cents=c) for b, c in amounts.items() if c > 0],
        leftover_cents=remaining,
    )
