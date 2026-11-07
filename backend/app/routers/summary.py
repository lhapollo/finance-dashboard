from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import CategoryTotal, MonthSummary, PeriodCategoryTotal, ReimbursementSummary
from app.services.summaries import (
    add_months,
    month_start,
    month_summary,
    spending_by_category,
    spending_over_time,
    waiting_to_be_reimbursed,
)

router = APIRouter(prefix="/summary", tags=["summary"])

SessionDep = Annotated[Session, Depends(get_session)]
# "2026-10". Leave it out to mean the current month.
MonthParam = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-10"])]


def _parse_month(month: str | None) -> date:
    if month is None:
        return month_start(date.today())
    year, m = month.split("-")
    return date(int(year), int(m), 1)


@router.get("/month")
def get_month_summary(session: SessionDep, month: MonthParam = None) -> MonthSummary:
    """The summary cards: spent, income and net for one month, and spending vs the month before."""
    return month_summary(session, _parse_month(month))


@router.get("/categories")
def get_spending_by_category(
    session: SessionDep,
    start: date | None = None,
    end: date | None = None,
) -> list[CategoryTotal]:
    """Spending per category, largest first. start is included, end isn't.
    Leave both out for the current month."""
    this_month = month_start(date.today())
    start = start or this_month
    end = end or add_months(start, 1)
    if end <= start:
        raise HTTPException(400, "end must be after start")
    return spending_by_category(session, start, end)


@router.get("/over-time")
def get_spending_over_time(
    session: SessionDep,
    group_by: Literal["month", "year"] = "month",
    months: Annotated[int, Query(ge=1, le=120)] = 12,
    month: MonthParam = None,
) -> list[PeriodCategoryTotal]:
    """Spending per category per month: the `months` months ending with `month` (default:
    the last 12, up to this month). With group_by=year: every year up to `month`'s year."""
    last = _parse_month(month)
    if group_by == "month":
        start, end = add_months(last, -(months - 1)), add_months(last, 1)
    else:
        start, end = date(1900, 1, 1), date(last.year + 1, 1, 1)
    return spending_over_time(session, start, end, group_by)


@router.get("/reimbursements")
def get_reimbursements(session: SessionDep) -> ReimbursementSummary:
    """Money I'm still owed for reimbursable purchases, over all time."""
    return waiting_to_be_reimbursed(session)
