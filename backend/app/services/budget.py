"""Budget math: bucket balances and unassigned money.

Store facts, calculate the rest: only allocations (decisions I made) are saved. Balances,
the total in buckets and unassigned money are worked out fresh on every request.

  bucket balance   = its allocations - spending from it since the budget started
  unassigned money = available money + money I'm owed - everything in buckets

Money I'm owed is what's still waiting to be paid back on reimbursable purchases. Marking a
purchase reimbursable takes it out of its bucket's spending, but the money has really left
the account, so available money doesn't have it. It's still mine, so it counts; when the
payback arrives, it moves from "owed" to "available" and unassigned doesn't change. Only
purchases from accounts that available money is worked out from count, or a purchase that
never lowered available money would raise unassigned.

Which bucket spending comes out of is decided in summaries.py (_bucket), using the same
counting rules as the dashboard: transfers and reimbursable purchases don't count, refunds
and paybacks put money back, and split transactions count as their parts.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Allocation,
    Bucket,
    BudgetSettings,
    CategoryBucket,
    Transaction,
    TransactionSplit,
)
from app.schemas import BucketOut, BudgetOut, CategoryBucketOut
from app.services.categories import load_rules
from app.services.summaries import (
    INCOME_CATEGORIES,
    balance_account_ids,
    balance_summary,
    spending_by_category,
    spent_by_bucket,
    waiting_to_be_reimbursed,
)


def start_date(session: Session) -> date | None:
    settings = session.get(BudgetSettings, 1)
    return settings.start_date if settings else None


def _allocated(session: Session) -> dict[int, int]:
    """Each bucket's allocations in cents, by id (buckets with none included, as 0)."""
    rows = session.execute(
        select(Bucket.id, func.coalesce(func.sum(Allocation.amount_cents), 0))
        .outerjoin(Allocation, Allocation.bucket_id == Bucket.id)
        .group_by(Bucket.id)
    )
    return {bucket_id: int(total) for bucket_id, total in rows}


def _spent(session: Session) -> dict[int | None, int]:
    start = start_date(session)
    return {} if start is None else spent_by_bucket(session, start)


def bucket_balances(session: Session) -> dict[int, int]:
    """Each bucket's balance in cents (allocated - spent), by bucket id."""
    spent = _spent(session)
    return {b: total - spent.get(b, 0) for b, total in _allocated(session).items()}


def budget(session: Session) -> BudgetOut:
    allocated, spent = _allocated(session), _spent(session)
    buckets = session.scalars(select(Bucket).order_by(Bucket.archived, Bucket.id)).all()
    money = balance_summary(session)
    available = money.available_cents if money.as_of is not None else None
    owed = waiting_to_be_reimbursed(session, balance_account_ids(session))
    out = [_bucket_out(b, allocated[b.id], spent.get(b.id, 0)) for b in buckets]
    assigned = sum(b.balance_cents for b in out if not b.archived)
    return BudgetOut(
        start_date=start_date(session),
        available_cents=available,
        available_as_of=money.as_of,
        owed_to_me_cents=owed.waiting_cents,
        owed_to_me_count=owed.count,
        assigned_cents=assigned,
        unassigned_cents=None if available is None else available + owed.waiting_cents - assigned,
        unbucketed_spent_cents=spent.get(None, 0),
        buckets=out,
    )


def category_buckets(session: Session) -> list[CategoryBucketOut]:
    """Every spending category that has a default bucket or spending since the start, with
    both. Biggest spending first, so the categories that matter most are on top."""
    defaults = dict(
        session.execute(select(CategoryBucket.category, CategoryBucket.bucket_id)).all()
    )
    start = start_date(session)
    spent = (
        {}
        if start is None
        else {c.category: c.total_cents for c in spending_by_category(session, start, date.max)}
    )
    categories = (defaults.keys() | spent.keys()) - set(INCOME_CATEGORIES)
    return sorted(
        (
            CategoryBucketOut(category=c, bucket_id=defaults.get(c), spent_cents=spent.get(c, 0))
            for c in categories
        ),
        key=lambda c: (-c.spent_cents, c.category),
    )


def _bucket_out(b: Bucket, allocated: int, spent: int) -> BucketOut:
    balance = allocated - spent
    progress = None
    if b.type == "goal" and b.target_amount_cents:
        progress = max(0, min(100, balance * 100 // b.target_amount_cents))
    return BucketOut(
        id=b.id,
        name=b.name,
        type=b.type,
        target_amount_cents=b.target_amount_cents,
        target_date=b.target_date,
        archived=b.archived,
        allocated_cents=allocated,
        spent_cents=spent,
        balance_cents=balance,
        progress_pct=progress,
    )


def known_categories(session: Session) -> set[str]:
    """Categories in the rule files or on any transaction or split part."""
    try:
        from_rules = {r.category for r in load_rules()}
    except ValueError:  # a typo in a rules file; the transactions still name categories
        from_rules = set()
    used = session.scalars(select(Transaction.category).distinct()).all()
    in_parts = session.scalars(select(TransactionSplit.category).distinct()).all()
    return from_rules | set(used) | set(in_parts)


def link_matching_category(session: Session, bucket: Bucket) -> None:
    """A bucket named like a spending category ("Dining") becomes that category's default
    bucket, if the category doesn't have one yet. A default I picked is never replaced."""
    category = bucket.name.strip().lower()
    if category in INCOME_CATEGORIES or session.get(CategoryBucket, category) is not None:
        return
    if category in known_categories(session):
        session.flush()  # the bucket needs its id
        session.add(CategoryBucket(category=category, bucket_id=bucket.id))
