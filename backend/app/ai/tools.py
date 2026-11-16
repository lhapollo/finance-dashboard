"""The tools the AI can call: plain functions over the database.

The AI never does the math. It reads a question, picks a tool and its arguments, and
explains what the tool returns. Every number in an answer comes from here, calculated with
the same rules as the dashboard (transfers and reimbursable purchases don't count, refunds
lower spending, and so on).

Tools return amounts already written out as dollars ("$1,234.56"), and any comparison
(difference, percent change, "enough or not") is worked out here too, so the AI only ever
repeats numbers, never computes them.

Each tool has: a description and parameter schema (what the AI sees), a Pydantic model that
checks the AI's arguments, and the function that runs.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.services.budget import budget, known_categories
from app.services.format import dollars
from app.services.summaries import (
    INCOME_CATEGORIES,
    balance_summary,
    pending_by_account,
    spending_by_merchant,
    spending_total,
    spent_and_income,
)


class ToolError(Exception):
    """A problem the AI can fix by calling the tool differently; sent back to it as-is."""


# --- Arguments -----------------------------------------------------------------------------


class DateRange(BaseModel):
    start_date: date
    end_date: date  # included

    @field_validator("end_date")
    @classmethod
    def after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start is not None and v < start:
            raise ValueError("end_date is before start_date")
        return v

    @property
    def end_exclusive(self) -> date:
        return self.end_date + timedelta(days=1)


class SpendingArgs(DateRange):
    categories: list[str] = Field(default_factory=list)
    merchant: str | None = None


class CompareArgs(BaseModel):
    first_start_date: date
    first_end_date: date
    second_start_date: date
    second_end_date: date
    categories: list[str] = Field(default_factory=list)
    merchant: str | None = None


class TopMerchantsArgs(DateRange):
    categories: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)


class FindArgs(BaseModel):
    search: str | None = None
    categories: list[str] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=10, ge=1, le=25)


class AffordArgs(BaseModel):
    amount_dollars: float = Field(gt=0)
    bucket: str | None = None


class NoArgs(BaseModel):
    pass


# --- The tools -----------------------------------------------------------------------------


def _check_categories(session: Session, categories: list[str]) -> list[str]:
    wanted = [c.strip().lower() for c in categories if c.strip()]
    known = known_categories(session)
    unknown = [c for c in wanted if c not in known]
    if unknown:
        spending = sorted(known - set(INCOME_CATEGORIES) - {"uncategorized"})
        raise ToolError(f"unknown categories {unknown}; use some of: {', '.join(spending)}")
    return wanted


def get_spending(session: Session, a: SpendingArgs) -> dict[str, Any]:
    categories = _check_categories(session, a.categories)
    total, purchases = spending_total(
        session, a.start_date, a.end_exclusive, categories or None, a.merchant
    )
    return {
        "start_date": a.start_date.isoformat(),
        "end_date": a.end_date.isoformat(),
        "categories": categories or "all spending",
        "merchant": a.merchant or "any",
        "spent": dollars(total),
        "purchases": purchases,
    }


def compare_spending(session: Session, a: CompareArgs) -> dict[str, Any]:
    first = SpendingArgs(
        start_date=a.first_start_date,
        end_date=a.first_end_date,
        categories=a.categories,
        merchant=a.merchant,
    )
    second = SpendingArgs(
        start_date=a.second_start_date,
        end_date=a.second_end_date,
        categories=a.categories,
        merchant=a.merchant,
    )
    categories = _check_categories(session, a.categories)
    one, _ = spending_total(
        session, first.start_date, first.end_exclusive, categories or None, a.merchant
    )
    two, _ = spending_total(
        session, second.start_date, second.end_exclusive, categories or None, a.merchant
    )
    change = two - one
    first_name = _period_name(first.start_date, first.end_date)
    second_name = _period_name(second.start_date, second.end_date)
    # Written out in full, so there's no "less than what?" for the AI to get backwards.
    if change == 0:
        comparison = f"{second_name}: the same as {first_name} ({dollars(two)})"
    else:
        direction = "more" if change > 0 else "less"
        percent = f", {abs(change) / one * 100:.1f}% {direction}" if one else ""
        comparison = (
            f"{second_name}: {dollars(two)}, which is {dollars(abs(change))} {direction} than "
            f"{first_name} ({dollars(one)}){percent}"
        )
    return {
        "categories": categories or "all spending",
        "merchant": a.merchant or "any",
        "first_period": first_name,
        "first_spent": dollars(one),
        "second_period": second_name,
        "second_spent": dollars(two),
        "comparison": comparison,
    }


def _period_name(start: date, end: date) -> str:
    """ "October 2026" for a whole calendar month, otherwise "2026-10-03 to 2026-10-17"."""
    whole_month = start.day == 1 and (end + timedelta(days=1)).day == 1 and start.month == end.month
    return f"{start:%B %Y}" if whole_month else f"{start} to {end}"


def get_income(session: Session, a: DateRange) -> dict[str, Any]:
    spent, income = spent_and_income(session, a.start_date, a.end_exclusive)
    return {
        "start_date": a.start_date.isoformat(),
        "end_date": a.end_date.isoformat(),
        "income": dollars(income),
        "spent": dollars(spent),
        "net": dollars(income - spent),
    }


def top_merchants(session: Session, a: TopMerchantsArgs) -> dict[str, Any]:
    categories = _check_categories(session, a.categories)
    rows = spending_by_merchant(session, a.start_date, a.end_exclusive, categories or None, a.limit)
    return {
        "start_date": a.start_date.isoformat(),
        "end_date": a.end_date.isoformat(),
        "merchants": [
            {"merchant": m, "spent": dollars(total), "visits": visits} for m, total, visits in rows
        ],
    }


def find_transactions(session: Session, a: FindArgs) -> dict[str, Any]:
    categories = _check_categories(session, a.categories)
    query = (
        select(Transaction).join(Account).order_by(Transaction.date.desc(), Transaction.id.desc())
    )
    if a.search:
        query = query.where(
            or_(
                Transaction.description.icontains(a.search, autoescape=True),
                Transaction.raw_description.icontains(a.search, autoescape=True),
            )
        )
    if categories:
        query = query.where(Transaction.category.in_(categories))
    if a.start_date:
        query = query.where(Transaction.date >= a.start_date)
    if a.end_date:
        query = query.where(Transaction.date <= a.end_date)
    rows = session.scalars(query.limit(a.limit)).all()
    return {
        "transactions": [
            {
                "date": t.date.isoformat(),
                "description": t.description,
                "amount": dollars(t.amount_cents),  # negative = money out
                "category": t.category,
                "account": t.account.name,
                **({"pending": True} if t.pending else {}),
                **({"transfer": True} if t.is_transfer else {}),
            }
            for t in rows
        ],
        "note": f"newest first, at most {a.limit}",
    }


def get_budget(session: Session, a: NoArgs) -> dict[str, Any]:
    b = budget(session)
    if b.start_date is None:
        raise ToolError("budgeting hasn't been set up yet (no buckets)")
    return {
        "budgeting_since": b.start_date.isoformat(),
        "unassigned": dollars(b.unassigned_cents) if b.unassigned_cents is not None else "unknown",
        "in_buckets": dollars(b.assigned_cents),
        "buckets": [
            {
                "name": x.name,
                "kind": x.type,
                "balance": dollars(x.balance_cents),
                "spent_since_start": dollars(x.spent_cents),
                **({"overspent": True} if x.balance_cents < 0 else {}),
                **(
                    {
                        "goal_target": dollars(x.target_amount_cents),
                        "goal_progress": f"{x.progress_pct}%",
                        "left_to_save": dollars(max(x.target_amount_cents - x.balance_cents, 0)),
                    }
                    if x.type == "goal" and x.target_amount_cents
                    else {}
                ),
                **({"goal_date": x.target_date.isoformat()} if x.target_date else {}),
            }
            for x in b.buckets
            if not x.archived
        ],
    }


def can_i_afford(session: Session, a: AffordArgs) -> dict[str, Any]:
    try:
        cents = int((Decimal(str(a.amount_dollars)) * 100).quantize(Decimal(1)))
    except InvalidOperation as e:
        raise ToolError("amount_dollars isn't a number") from e
    b = budget(session)
    if b.start_date is None:
        raise ToolError("budgeting hasn't been set up yet (no buckets)")
    unassigned = b.unassigned_cents or 0
    result: dict[str, Any] = {"amount": dollars(cents), "unassigned": dollars(unassigned)}

    if a.bucket:
        open_buckets = [x for x in b.buckets if not x.archived]
        wanted = a.bucket.strip().lower()
        match = [x for x in open_buckets if x.name.lower() == wanted] or [
            x for x in open_buckets if wanted in x.name.lower()
        ]
        if len(match) != 1:
            names = ", ".join(x.name for x in open_buckets)
            raise ToolError(f"no single bucket matches {a.bucket!r}; buckets are: {names}")
        x = match[0]
        in_bucket = max(x.balance_cents, 0)
        result |= {
            "bucket": x.name,
            "bucket_balance": dollars(x.balance_cents),
            "enough_in_bucket": cents <= in_bucket,
            "enough_with_unassigned_too": cents <= in_bucket + max(unassigned, 0),
            "short_by": dollars(max(cents - in_bucket - max(unassigned, 0), 0)),
        }
    else:
        result |= {
            "enough_unassigned": cents <= unassigned,
            "short_by": dollars(max(cents - unassigned, 0)),
        }
    return result


def get_balances(session: Session, a: NoArgs) -> dict[str, Any]:
    summary = balance_summary(session)
    if summary.as_of is None:
        raise ToolError("no bank balances yet (no bank connected through Plaid)")
    pending = pending_by_account(session)
    accounts = session.scalars(
        select(Account).where(Account.closed_on.is_(None), Account.balance_cents.is_not(None))
    ).all()
    return {
        "as_of": summary.as_of.isoformat(timespec="minutes"),
        "accounts": [
            {
                "name": acc.name,
                # Including pending transactions, like the totals.
                ("owed" if acc.type == "credit" else "balance"): dollars(
                    abs(acc.balance_cents + pending.get(acc.id, 0))
                ),
            }
            for acc in accounts
        ],
        "cash": dollars(summary.cash_cents),
        "owed_on_cards": dollars(summary.owed_cents),
        "available": dollars(summary.available_cents),
    }


# --- The registry the chat uses ------------------------------------------------------------

_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_CATEGORIES = {
    "type": "array",
    "items": {"type": "string"},
    "description": 'Optional. Only these categories, e.g. ["groceries", "dining"] for food.',
}
_MERCHANT = {
    "type": "string",
    "description": 'Optional. Only merchants whose name contains this, e.g. "Uber".',
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments, as the AI sees it
    args: type[BaseModel]
    run: Callable[[Session, Any], dict[str, Any]]

    def call(self, session: Session, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run with the AI's arguments. Mistakes come back as {"error": ...} so the AI can
        fix them and try again, instead of the whole question failing."""
        try:
            return self.run(session, self.args.model_validate(arguments))
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            return {"error": f"bad arguments: {problems}"}
        except ToolError as e:
            return {"error": str(e)}


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


TOOLS = [
    Tool(
        "get_spending",
        "Total spending between two dates (both included), optionally only some categories "
        "and/or a merchant. Refunds and paybacks are already subtracted; transfers between "
        "my own accounts and reimbursable work expenses aren't spending.",
        _object(
            {
                "start_date": _DATE,
                "end_date": _DATE,
                "categories": _CATEGORIES,
                "merchant": _MERCHANT,
            },
            ["start_date", "end_date"],
        ),
        SpendingArgs,
        get_spending,
    ),
    Tool(
        "compare_spending",
        "Spending in two periods side by side, with the difference and percent change "
        "already calculated. Use for 'X vs Y' questions.",
        _object(
            {
                "first_start_date": _DATE,
                "first_end_date": _DATE,
                "second_start_date": _DATE,
                "second_end_date": _DATE,
                "categories": _CATEGORIES,
                "merchant": _MERCHANT,
            },
            ["first_start_date", "first_end_date", "second_start_date", "second_end_date"],
        ),
        CompareArgs,
        compare_spending,
    ),
    Tool(
        "get_income",
        "Income (pay, interest, cashback), spending and net (income minus spending) between "
        "two dates, both included.",
        _object({"start_date": _DATE, "end_date": _DATE}, ["start_date", "end_date"]),
        DateRange,
        get_income,
    ),
    Tool(
        "top_merchants",
        "Where money went: merchants by total spent between two dates, biggest first, with "
        "how many visits.",
        _object(
            {
                "start_date": _DATE,
                "end_date": _DATE,
                "categories": _CATEGORIES,
                "limit": {"type": "integer", "description": "How many (1-20, default 5)."},
            },
            ["start_date", "end_date"],
        ),
        TopMerchantsArgs,
        top_merchants,
    ),
    Tool(
        "find_transactions",
        "Look up individual transactions, newest first: by text in the description, "
        "category and/or dates. For questions like 'when did I last buy X' or 'what was that "
        "$40 charge'. Not for totals: use get_spending for those.",
        _object(
            {
                "search": {"type": "string", "description": "Optional. Text in the description."},
                "categories": _CATEGORIES,
                "start_date": {**_DATE, "description": "Optional. YYYY-MM-DD"},
                "end_date": {**_DATE, "description": "Optional. YYYY-MM-DD"},
                "limit": {"type": "integer", "description": "How many (1-25, default 10)."},
            },
            [],
        ),
        FindArgs,
        find_transactions,
    ),
    Tool(
        "get_budget",
        "The budget: each bucket's balance, what's been spent from it, goal progress, and "
        "unassigned money (money with no bucket yet).",
        _object({}, []),
        NoArgs,
        get_budget,
    ),
    Tool(
        "can_i_afford",
        "Whether an amount fits: in a bucket (if given), and with unassigned money too. "
        "Without a bucket, checks unassigned money only.",
        _object(
            {
                "amount_dollars": {"type": "number", "description": "e.g. 49.99"},
                "bucket": {"type": "string", "description": "Optional. A bucket's name."},
            },
            ["amount_dollars"],
        ),
        AffordArgs,
        can_i_afford,
    ),
    Tool(
        "get_balances",
        "Account balances right now from the bank (including pending transactions), cash, "
        "owed on credit cards, and available money (cash minus card debt).",
        _object({}, []),
        NoArgs,
        get_balances,
    ),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def spending_categories(session: Session) -> list[str]:
    """Category names the AI may use, for the instructions."""
    return sorted(known_categories(session) - set(INCOME_CATEGORIES))
