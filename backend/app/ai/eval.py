"""How often does the Ask page get it right? Asks real questions about the demo data and
checks each answer against the right numbers, worked out by code.

    docker compose exec backend-demo python -m app.ai.eval            # all questions
    docker compose exec backend-demo python -m app.ai.eval --only 3   # just question 3

Only runs on the demo database (fake data), and calls the real AI, so it's slow on a free
tier: it waits out rate limits instead of failing.

An answer passes when it contains every expected piece (an amount like "$1,007.35", a
merchant's name, "yes"/"no"...), ignoring capitalization. That's strict on purpose: a
right-sounding answer with a wrong number fails.
"""

import argparse
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.ai.chat import ask, on_demo_data
from app.ai.providers import AIError, AITimeout, RateLimited, get_provider
from app.ai.tools import TOOLS_BY_NAME
from app.db import SessionLocal
from app.services.clock import today


@dataclass
class Case:
    question: str
    # Works out the expected pieces from the database, the same way a person checking by
    # hand would: by calling the tools with the right arguments.
    expected: Callable[[Session], list[str]]


def _tool(session: Session, name: str, **arguments):
    result = TOOLS_BY_NAME[name].call(session, arguments)
    assert "error" not in result, result
    return result


def _month(offset: int) -> tuple[date, date]:
    """(first day, last day) of the month `offset` months from this one (-1: last month)."""
    first = today().replace(day=1)
    for _ in range(-offset):
        first = (first - timedelta(days=1)).replace(day=1)
    next_first = (first + timedelta(days=32)).replace(day=1)
    return first, next_first - timedelta(days=1)


def _spent(session, months: int = -1, **filters) -> str:
    start, end = _month(months)
    return _tool(session, "get_spending", start_date=start, end_date=end, **filters)["spent"]


def _bucket(session, name):
    return next(b for b in _tool(session, "get_budget")["buckets"] if b["name"] == name)


def _cases() -> list[Case]:
    m2 = _month(-2)[0]
    m3 = _month(-3)[0]
    return [
        Case("How much did I spend last month?", lambda s: [_spent(s)]),
        Case(
            "How much did I spend on groceries last month?",
            lambda s: [_spent(s, categories=["groceries"])],
        ),
        Case(
            "How much did I spend eating out last month?",
            lambda s: [_spent(s, categories=["dining"])],
        ),
        Case(
            "How much did I spend on food last month?",
            lambda s: [_spent(s, categories=["groceries", "dining"])],
        ),
        Case("How much have I spent so far this month?", lambda s: [_spent(s, months=0)]),
        Case(
            f"How much did I spend on transport in {m2:%B}?",
            lambda s: [_spent(s, months=-2, categories=["transport"])],
        ),
        Case(
            f"How much did I spend in total in {m3:%B %Y}?",
            lambda s: [_spent(s, months=-3)],
        ),
        Case(
            "Compare my dining spending last month to the month before.",
            lambda s: [_spent(s, categories=["dining"]), _spent(s, -2, categories=["dining"])],
        ),
        Case(
            "Did I spend more or less on groceries last month than the month before?",
            lambda s: [
                "more"
                if _cents(_spent(s, categories=["groceries"]))
                > _cents(_spent(s, -2, categories=["groceries"]))
                else "less"
            ],
        ),
        Case(
            "What was my income last month?",
            lambda s: [_income(s)["income"]],
        ),
        Case(
            "What was my net last month, income minus spending?",
            lambda s: [_income(s)["net"]],
        ),
        Case(
            "Where did I spend the most money last month?",
            lambda s: [_top(s)[0]["merchant"]],
        ),
        Case(
            "Which grocery store did I spend the most at last month?",
            lambda s: [_top(s, categories=["groceries"])[0]["merchant"]],
        ),
        Case(
            "How much did I spend at Tim Hortons last month?",
            lambda s: [_spent(s, merchant="Tim Hortons")],
        ),
        Case(
            "How many times did I go to Tim Hortons last month?",
            lambda s: [str(_spending(s, merchant="Tim Hortons")["purchases"])],
        ),
        Case("How much is my Netflix subscription?", lambda s: ["$16.49"]),
        Case("How much does Spotify charge me?", lambda s: ["$11.99"]),
        Case(
            "How much is left in my Groceries bucket?",
            lambda s: [_bucket(s, "Groceries")["balance"]],
        ),
        Case(
            "How much unassigned money do I have?",
            lambda s: [_tool(s, "get_budget")["unassigned"]],
        ),
        Case(
            "Can I afford a $50 purchase from my Fun bucket?",
            lambda s: [
                "yes"
                if _tool(s, "can_i_afford", amount_dollars=50, bucket="Fun")["enough_in_bucket"]
                else "no"
            ],
        ),
        Case(
            "Could I pay for a $5,000 trip out of my Switch 2 bucket?",
            lambda s: ["no"],
        ),
        Case(
            "How much more do I need to save for the Switch 2?",
            lambda s: [_bucket(s, "Switch 2")["left_to_save"]],
        ),
        Case(
            "Which of my buckets are overspent?",
            lambda s: (
                [b["name"] for b in _tool(s, "get_budget")["buckets"] if b.get("overspent")]
                or ["none"]
            ),
        ),
        Case(
            "How much money do I have available right now?",
            lambda s: [_tool(s, "get_balances")["available"]],
        ),
        Case(
            "How much do I owe on my Mastercard?",
            lambda s: [
                next(
                    a["owed"]
                    for a in _tool(s, "get_balances")["accounts"]
                    if a["name"] == "Tangerine Mastercard"
                )
            ],
        ),
    ]


def _cents(dollars: str) -> int:
    return round(float(dollars.replace("$", "").replace(",", "")) * 100)


def _spending(session, months=-1, **filters):
    start, end = _month(months)
    return _tool(session, "get_spending", start_date=start, end_date=end, **filters)


def _income(session):
    start, end = _month(-1)
    return _tool(session, "get_income", start_date=start, end_date=end)


def _top(session, **filters):
    start, end = _month(-1)
    return _tool(session, "top_merchants", start_date=start, end_date=end, **filters)["merchants"]


# Natural ways of saying yes or no, so "You cannot pay for that" counts as "no".
_SAYS = {
    "yes": r"\byes\b|\byou can\b|\bcan afford\b|\bthere'?s enough\b",
    "no": r"\bno\b|\bcannot\b|\bcan'?t\b|\bnot enough\b|\bisn'?t enough\b|\bshort by\b",
    "more": r"\bmore\b",
    "less": r"\bless\b",
    "none": r"\bnone\b|\bno buckets?\b",
}


def passes(answer: str, expected: list[str]) -> bool:
    """Every expected piece is in the answer (any capitalization). Yes/no and more/less
    accept natural wording; a merchant name may leave out a bank's "e-Transfer to" prefix."""
    text = answer.lower()
    for piece in expected:
        piece = piece.lower()
        if piece in _SAYS:
            if not re.search(_SAYS[piece], text):
                return False
        elif piece.removeprefix("e-transfer to ") not in text:
            return False
    return True


# Waiting out a short burst limit is fine; anything longer means the daily allowance is
# gone, and sleeping for hours helps nobody.
_MAX_WAIT = 120


def _stop_early(passed: int, asked: int, reason: str) -> None:
    score = f"{passed}/{asked} correct so far" if asked else "no questions finished"
    raise SystemExit(f"\nStopped: {reason}.\n{score}. Run the rest later with --start.")


def main() -> None:
    # Print each result as soon as it's graded, even when output goes to a file or a pipe.
    sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description="Score the Ask page on the demo data.")
    parser.add_argument("--only", type=int, help="run just this question (1-based)")
    parser.add_argument("--start", type=int, default=1, help="start at this question (1-based)")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds between questions")
    args = parser.parse_args()
    if not on_demo_data():
        raise SystemExit("the eval only runs on the demo database (fake data)")

    provider = get_provider()
    cases = _cases()
    picked = (
        [(args.only, cases[args.only - 1])]
        if args.only
        else list(enumerate(cases, 1))[args.start - 1 :]
    )
    passed = 0
    for number, case in picked:
        with SessionLocal() as session:
            expected = case.expected(session)
            answer = None
            for _ in range(5):
                try:
                    answer = ask(session, provider, case.question, []).text
                    break
                except RateLimited as e:
                    if e.retry_after > _MAX_WAIT:
                        _stop_early(passed, number - picked[0][0], str(e))
                    print(f"   (rate limited, waiting {e.retry_after:.0f}s)")
                    time.sleep(e.retry_after + 1)
                except AITimeout:
                    print("   (Gemini timed out, trying again)")
                except AIError as e:
                    answer = f"ERROR: {e}"
                    break
        if answer is None:
            _stop_early(passed, number - picked[0][0], "kept hitting the rate limit")
        ok = passes(answer, expected)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'} {number:2}. {case.question}")
        if not ok:
            print(f"        expected: {expected}")
            print(f"        answer:   {answer}")
        time.sleep(args.pause)

    total = len(picked)
    print(f"\n{passed}/{total} correct ({passed / total * 100:.0f}%)")


if __name__ == "__main__":
    main()
