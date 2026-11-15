"""Buckets and the budget: create buckets, do the fresh-start split, assign and move money.

Every change returns the whole budget, so the page can redraw from one response.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Allocation, Bucket, BudgetSettings
from app.schemas import AssignIn, BucketIn, BucketUpdate, BudgetOut, BudgetStart, MoveIn
from app.services.budget import bucket_balances, budget, start_date
from app.services.format import dollars

router = APIRouter(tags=["budget"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/budget")
def get_budget(session: SessionDep) -> BudgetOut:
    return budget(session)


@router.post("/buckets", status_code=status.HTTP_201_CREATED)
def create_bucket(body: BucketIn, session: SessionDep) -> BudgetOut:
    if body.type == "goal" and body.target_amount_cents is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "a goal needs a target amount")
    session.add(Bucket(**body.model_dump()))
    _commit_unique_name(session, body.name)
    return budget(session)


@router.patch("/buckets/{bucket_id}")
def update_bucket(bucket_id: int, body: BucketUpdate, session: SessionDep) -> BudgetOut:
    bucket = _bucket_or_404(session, bucket_id)
    changes = body.model_dump(exclude_unset=True)

    if changes.get("archived") and not bucket.archived:
        # Its leftover goes back to unassigned, so archived buckets never hold money.
        leftover = bucket_balances(session)[bucket.id]
        if leftover != 0:
            session.add(
                Allocation(
                    bucket=bucket,
                    amount_cents=-leftover,
                    date=date.today(),
                    kind="archive",
                    note="Leftover back to unassigned",
                )
            )
    if "name" in changes:
        changes["name"] = " ".join(changes["name"].split())
    if bucket.type == "goal" and "target_amount_cents" in changes:
        if changes["target_amount_cents"] is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "a goal needs a target amount")
    for field, value in changes.items():
        setattr(bucket, field, value)
    _commit_unique_name(session, bucket.name)
    return budget(session)


@router.delete("/buckets/{bucket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bucket(bucket_id: int, session: SessionDep) -> None:
    """Only for a bucket that never held money, e.g. one made by mistake. Others are
    archived instead, so their history stays."""
    bucket = _bucket_or_404(session, bucket_id)
    if bucket.allocations:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{bucket.name} has history; archive it instead"
        )
    session.delete(bucket)
    session.commit()


@router.post("/budget/start")
def start_budget(body: BudgetStart, session: SessionDep) -> BudgetOut:
    """The fresh start (or starting over): from start_date, split today's available money
    across buckets. Replaces every earlier allocation."""
    if body.start_date > date.today():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the start date can't be in the future")
    ids = [o.bucket_id for o in body.opening]
    if len(ids) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "a bucket is listed twice")
    for bucket_id in ids:
        if _bucket_or_404(session, bucket_id).archived:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "can't put money in an archived bucket"
            )

    available = budget(session).available_cents
    if available is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "the budget needs to know how much money you have: connect a bank on the "
            "Accounts page first",
        )
    total = sum(o.amount_cents for o in body.opening)
    if total > available:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"that's {dollars(total)}, but you have {dollars(available)} available",
        )

    for old in session.scalars(select(Allocation)):
        session.delete(old)
    settings = session.get(BudgetSettings, 1) or BudgetSettings(id=1, start_date=body.start_date)
    settings.start_date = body.start_date
    session.add(settings)
    for o in body.opening:
        if o.amount_cents > 0:
            session.add(
                Allocation(
                    bucket_id=o.bucket_id,
                    amount_cents=o.amount_cents,
                    date=body.start_date,
                    kind="opening_balance",
                )
            )
    session.commit()
    return budget(session)


@router.post("/budget/assign")
def assign(body: AssignIn, session: SessionDep) -> BudgetOut:
    """Unassigned money into a bucket (positive amount), or back out of it (negative)."""
    _require_started(session)
    bucket = _open_bucket(session, body.bucket_id)
    if body.amount_cents == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "amount is zero")

    current = budget(session)
    if body.amount_cents > 0:
        unassigned = current.unassigned_cents or 0
        if body.amount_cents > unassigned:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"only {dollars(max(unassigned, 0))} is unassigned",
            )
    else:
        balance = bucket_balances(session)[bucket.id]
        if -body.amount_cents > balance:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{bucket.name} only has {dollars(max(balance, 0))}"
            )

    session.add(
        Allocation(
            bucket=bucket,
            amount_cents=body.amount_cents,
            date=date.today(),
            kind="assign",
            note=body.note,
        )
    )
    session.commit()
    return budget(session)


@router.post("/budget/move")
def move(body: MoveIn, session: SessionDep) -> BudgetOut:
    """Two allocations: minus on one bucket, plus on the other. Unassigned doesn't change."""
    _require_started(session)
    if body.from_bucket_id == body.to_bucket_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "pick two different buckets")
    source = _open_bucket(session, body.from_bucket_id)
    target = _open_bucket(session, body.to_bucket_id)
    balance = bucket_balances(session)[source.id]
    if body.amount_cents > balance:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{source.name} only has {dollars(max(balance, 0))}"
        )
    today = date.today()
    note = body.note or f"{source.name} → {target.name}"
    session.add_all(
        [
            Allocation(
                bucket=source, amount_cents=-body.amount_cents, date=today, kind="move", note=note
            ),
            Allocation(
                bucket=target, amount_cents=body.amount_cents, date=today, kind="move", note=note
            ),
        ]
    )
    session.commit()
    return budget(session)


def _bucket_or_404(session: Session, bucket_id: int) -> Bucket:
    bucket = session.get(Bucket, bucket_id)
    if bucket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no bucket with id {bucket_id}")
    return bucket


def _open_bucket(session: Session, bucket_id: int) -> Bucket:
    bucket = _bucket_or_404(session, bucket_id)
    if bucket.archived:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{bucket.name} is archived")
    return bucket


def _require_started(session: Session) -> None:
    if start_date(session) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "set up the budget first")


def _commit_unique_name(session: Session, name: str) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"there's already a bucket called {name}"
        ) from None
