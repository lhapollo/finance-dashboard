"""Dashboard numbers, calculated fresh from transactions every time (nothing is stored).

Transfers between my own accounts are left out of everything here: they aren't spending
or income. Spending is reported as a positive number of cents.

Only the income categories count as income. Money in under any other category lowers that
category's spending instead: a $60 shirt returned for $60 is $0 of shopping, not $60 of
shopping plus $60 of income. A payback linked to a purchase (reimburses_id) counts in the
purchase's category and month, so a dinner I paid $80 for and got $40 back for is $40 of
dining in the month of the dinner. A category can end up below zero in a month where
refunds outweigh purchases.

A reimbursable purchase (someone will pay all of it back, e.g. a work dinner) isn't my
spending, so it's left out, and so are the paybacks linked to it: they aren't income.

A split transaction counts as its parts instead of as a whole: a $1,345 paycheck split into
$1,300 of income and a $45 payback for a work dinner is $1,300 of income. Everything here
reads "entries", which are whole transactions that aren't split plus the parts of those
that are.
"""

from datetime import date, timedelta
from typing import Literal

from sqlalchemy import Date, case, cast, exists, func, literal, select, union_all
from sqlalchemy.orm import Session, aliased

from app.models import Account, Transaction, TransactionSplit
from app.schemas import (
    AccountActivity,
    CategoryTotal,
    MonthSummary,
    PeriodCategoryTotal,
    ReimbursementSummary,
)

INCOME_CATEGORIES = ("income", "rewards")

_is_split = exists().where(TransactionSplit.transaction_id == Transaction.id)
_entries = union_all(
    select(
        Transaction.date,
        Transaction.amount_cents,
        Transaction.category,
        Transaction.reimburses_id,
        Transaction.is_transfer,
        Transaction.reimbursable,
    ).where(~_is_split),
    # A part takes its date and transfer flag from its transaction. A split transaction
    # can't be reimbursable, so neither can its parts.
    select(
        Transaction.date,
        TransactionSplit.amount_cents,
        TransactionSplit.category,
        TransactionSplit.reimburses_id,
        Transaction.is_transfer,
        literal(False),
    ).join(Transaction, TransactionSplit.transaction_id == Transaction.id),
).subquery("entries")

_amount = _entries.c.amount_cents
_purchase = aliased(Transaction)  # the purchase an entry pays back, if any
_category = func.coalesce(_purchase.category, _entries.c.category)
_date = func.coalesce(_purchase.date, _entries.c.date)
_is_income = _category.in_(INCOME_CATEGORIES)
# On a payback, whether its purchase is reimbursable; otherwise the entry's own flag.
_reimbursable = func.coalesce(_purchase.reimbursable, _entries.c.reimbursable)
_spent = func.coalesce(func.sum(case((_is_income, 0), else_=-_amount)), 0)
_income = func.coalesce(func.sum(case((_is_income, _amount), else_=0)), 0)


def _counted(*columns, start: date, end: date):
    """SELECT columns over the entries that count between start (included) and end (not):
    [2026-10-01, 2026-11-01) is all of October. Paybacks are dated by their purchase."""
    return (
        select(*columns)
        .select_from(_entries)
        .outerjoin(_purchase, _entries.c.reimburses_id == _purchase.id)
        .where(
            _date >= start,
            _date < end,
            _entries.c.is_transfer.is_(False),
            _reimbursable.is_(False),
        )
    )


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    """First day of the month `months` after (or before, if negative) d's month."""
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def spent_and_income(session: Session, start: date, end: date) -> tuple[int, int]:
    spent, income = session.execute(_counted(_spent, _income, start=start, end=end)).one()
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
    """Largest first. Income categories aren't spending, so they're left out."""
    category = _category.label("category")
    total = (-func.sum(_amount)).label("total")
    rows = session.execute(
        _counted(category, total, start=start, end=end)
        .where(~_is_income)
        .group_by(category)
        .having(func.sum(_amount) != 0)  # a fully refunded purchase leaves nothing to show
        .order_by(total.desc(), category)
    )
    return [CategoryTotal(category=c, total_cents=t) for c, t in rows]


def spending_over_time(
    session: Session, start: date, end: date, unit: Literal["month", "year"]
) -> list[PeriodCategoryTotal]:
    """One row per (period, category) with spending or refunds, oldest period first."""
    period = cast(func.date_trunc(unit, _date), Date).label("period")
    category = _category.label("category")
    total = (-func.sum(_amount)).label("total")
    rows = session.execute(
        _counted(period, category, total, start=start, end=end)
        .where(~_is_income)
        .group_by(period, category)
        .having(func.sum(_amount) != 0)
        .order_by(period, total.desc(), category)
    )
    return [PeriodCategoryTotal(period=p, category=c, total_cents=t) for p, c, t in rows]


def waiting_to_be_reimbursed(session: Session) -> ReimbursementSummary:
    """Money I'm owed: reimbursable purchases minus the paybacks linked to them so far, over
    all time (it's still owed whenever the purchase was)."""
    paid_back = (
        select(func.sum(_entries.c.amount_cents))
        .where(_entries.c.reimburses_id == Transaction.id)
        .correlate(Transaction)
        .scalar_subquery()
    )
    owed = (-Transaction.amount_cents - func.coalesce(paid_back, 0)).label("owed")
    waiting = (
        select(owed)
        .where(Transaction.reimbursable.is_(True), Transaction.is_transfer.is_(False))
        .subquery()
    )
    total, count = session.execute(
        select(func.coalesce(func.sum(waiting.c.owed), 0), func.count()).where(waiting.c.owed > 0)
    ).one()
    return ReimbursementSummary(waiting_cents=int(total), count=count)


def account_activity(session: Session, month: date) -> list[AccountActivity]:
    """Each account's money in and out for one month, as the bank shows it. Unlike every
    other number here, this counts transfers, refunds and splits as plain transactions: it's
    for checking against bank statements, not for budgeting."""
    start, end = month_start(month), add_months(month_start(month), 1)
    in_month = Transaction.date.between(start, end - timedelta(days=1))
    amount = Transaction.amount_cents
    rows = session.execute(
        select(
            Account,
            func.coalesce(func.sum(case((in_month & (amount > 0), amount))), 0),
            func.coalesce(func.sum(case((in_month & (amount < 0), -amount))), 0),
            func.count(case((in_month, 1))),
            func.min(Transaction.date),
            func.max(Transaction.date),
        )
        .outerjoin(Transaction, Transaction.account_id == Account.id)
        .group_by(Account.id)
        .order_by(Account.id)
    )
    return [
        AccountActivity(
            id=a.id,
            name=a.name,
            institution=a.institution,
            type=a.type,
            money_in_cents=int(money_in),
            money_out_cents=int(money_out),
            count=count,
            first_date=first,
            last_date=last,
            plaid_linked=a.plaid_account_id is not None,
        )
        for a, money_in, money_out, count, first, last in rows
    ]
