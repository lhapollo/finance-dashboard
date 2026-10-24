"""Dashboard numbers, calculated fresh from transactions every time (nothing is stored).

Transfers between my own accounts are left out of everything here: they aren't spending
or income. Spending is reported as a positive number of cents.
"""

from datetime import date
from typing import Literal

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.schemas import CategoryTotal, MonthSummary, PeriodCategoryTotal

_amount = Transaction.amount_cents
_spent = func.coalesce(func.sum(case((_amount < 0, -_amount), else_=0)), 0)
_income = func.coalesce(func.sum(case((_amount > 0, _amount), else_=0)), 0)


def _in_range(start: date, end: date):
    """start is included, end is not: [2026-10-01, 2026-11-01) is all of October."""
    return (Transaction.date >= start, Transaction.date < end, Transaction.is_transfer.is_(False))


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    """First day of the month `months` after (or before, if negative) d's month."""
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def spent_and_income(session: Session, start: date, end: date) -> tuple[int, int]:
    spent, income = session.execute(select(_spent, _income).where(*_in_range(start, end))).one()
    return int(spent), int(income)


def month_summary(session: Session, month: date) -> MonthSummary:
    start = month_start(month)
    spent, income = spent_and_income(session, start, add_months(start, 1))
    previous, _ = spent_and_income(session, add_months(start, -1), start)
    return MonthSummary(
        month=start,
        spent_cents=spent,
        income_cents=income,
        net_cents=income - spent,
        previous_spent_cents=previous,
        change_pct=round((spent - previous) / previous * 100, 1) if previous else None,
    )


def spending_by_category(session: Session, start: date, end: date) -> list[CategoryTotal]:
    """Largest first."""
    total = (-func.sum(_amount)).label("total")
    rows = session.execute(
        select(Transaction.category, total)
        .where(*_in_range(start, end), _amount < 0)
        .group_by(Transaction.category)
        .order_by(total.desc(), Transaction.category)
    )
    return [CategoryTotal(category=c, total_cents=t) for c, t in rows]


def spending_over_time(
    session: Session, start: date, end: date, unit: Literal["month", "year"]
) -> list[PeriodCategoryTotal]:
    """One row per (period, category) that had spending, oldest period first."""
    period = cast(func.date_trunc(unit, Transaction.date), Date).label("period")
    total = (-func.sum(_amount)).label("total")
    rows = session.execute(
        select(period, Transaction.category, total)
        .where(*_in_range(start, end), _amount < 0)
        .group_by(period, Transaction.category)
        .order_by(period, total.desc(), Transaction.category)
    )
    return [PeriodCategoryTotal(period=p, category=c, total_cents=t) for p, c, t in rows]
