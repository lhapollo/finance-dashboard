"""Budget math: bucket balances and unassigned money.

Store facts, calculate the rest: only allocations (decisions I made) are saved. Balances,
the total in buckets and unassigned money are worked out fresh on every request.

  bucket balance   = its allocations (spending from buckets comes in a later step)
  unassigned money = available money - everything in buckets
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Allocation, Bucket, BudgetSettings
from app.schemas import BucketOut, BudgetOut
from app.services.summaries import balance_summary


def start_date(session: Session) -> date | None:
    settings = session.get(BudgetSettings, 1)
    return settings.start_date if settings else None


def bucket_balances(session: Session) -> dict[int, int]:
    """Each bucket's balance in cents, by bucket id (buckets with nothing in them included)."""
    rows = session.execute(
        select(Bucket.id, func.coalesce(func.sum(Allocation.amount_cents), 0))
        .outerjoin(Allocation, Allocation.bucket_id == Bucket.id)
        .group_by(Bucket.id)
    )
    return {bucket_id: int(total) for bucket_id, total in rows}


def budget(session: Session) -> BudgetOut:
    balances = bucket_balances(session)
    buckets = session.scalars(select(Bucket).order_by(Bucket.archived, Bucket.id)).all()
    money = balance_summary(session)
    available = money.available_cents if money.as_of is not None else None
    assigned = sum(balances[b.id] for b in buckets if not b.archived)
    return BudgetOut(
        start_date=start_date(session),
        available_cents=available,
        available_as_of=money.as_of,
        assigned_cents=assigned,
        unassigned_cents=None if available is None else available - assigned,
        buckets=[_bucket_out(b, balances[b.id]) for b in buckets],
    )


def unassigned_cents(session: Session) -> int | None:
    return budget(session).unassigned_cents


def _bucket_out(b: Bucket, balance: int) -> BucketOut:
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
        allocated_cents=balance,
        balance_cents=balance,
        progress_pct=progress,
    )
