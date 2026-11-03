"""Transfer detection: money moving between my own accounts is neither spending nor income."""

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

# A payment can take a few business days to land on the other side. CIBC credits a payment
# up to 4 days before Tangerine withdraws it when a weekend is in between.
MAX_DAYS_APART = 5

# How a credit card bill payment shows up on the card's own statement (checked against CIBC's
# real export). Anchored at the start, so a purchase like "DRIVE TEST PAYMENT" doesn't match.
_CARD_PAYMENT = re.compile(r"^(PRE[- ]?AUTHORIZED PAYMENT|PAYMENT THANK YOU)", re.IGNORECASE)

# Money a bank account sends to (or gets from) another of my own accounts, recognizable from
# the bank side alone (checked against Tangerine's real export). Paying off a card or credit
# line counts too: like a card payment, the spending happened when the card was used.
_OWN_TRANSFER = re.compile(
    r"^("
    r"(Recurring )?Internet (Deposit from|Withdrawal to) Tangerine"  # between Tangerine accounts
    r"|Tangerine Credit Card Payment"
    r"|EFT Withdrawal to WS Investments"  # to Wealthsimple
    r"|Bill Payment - .*(VISA|MASTERCARD|LINE OF CREDIT|AMERICAN EXPRESS|AMEX)"
    r")",
    re.IGNORECASE,
)


def detect_transfers(session: Session) -> int:
    """Mark transfers across all transactions; returns how many rows it newly marked.

    Safe to run as often as you like: it only ever adds transfer marks, and it never
    touches a row whose transfer flag you set by hand (transfer_source = "manual").
    """
    rows = session.scalars(
        select(Transaction).where(Transaction.transfer_source == "auto").order_by(Transaction.id)
    ).all()
    before = sum(t.is_transfer for t in rows)

    # 1. Transfers recognizable from one side alone: card payments as the card sees them, and
    #    bank-side moves to my own accounts. The other side may not be imported (yet).
    for t in rows:
        if is_card_payment(t) or is_own_transfer(t):
            t.is_transfer = True

    # 2. Pair up the two sides of a transfer between two imported accounts.
    _pair(rows)

    return sum(t.is_transfer for t in rows) - before


def is_card_payment(t: Transaction) -> bool:
    return (
        t.account.type == "credit"
        and t.amount_cents > 0
        and _CARD_PAYMENT.match(t.raw_description) is not None
    )


def is_own_transfer(t: Transaction) -> bool:
    return t.account.type != "credit" and _OWN_TRANSFER.match(t.raw_description) is not None


def _pair(rows: list[Transaction]) -> None:
    """Match money out of one account with the same amount into another, within a few days.

    The money-out side is never a credit card purchase: buying a $40 dinner on the card and a
    friend sending $40 to savings the next day would otherwise look like a transfer.
    """
    unpaired = [t for t in rows if t.transfer_pair_id is None]
    money_in_by_amount: dict[int, list[Transaction]] = defaultdict(list)
    for t in unpaired:
        if t.amount_cents > 0:
            money_in_by_amount[t.amount_cents].append(t)

    money_out = [t for t in unpaired if t.amount_cents < 0 and t.account.type != "credit"]
    for out in sorted(money_out, key=lambda t: (t.date, t.id)):
        candidates = [
            t
            for t in money_in_by_amount[-out.amount_cents]
            if t.account_id != out.account_id and abs((t.date - out.date).days) <= MAX_DAYS_APART
        ]
        if not candidates:
            continue
        # Closest date wins; ties go to the earlier-imported row, so results are repeatable.
        match = min(candidates, key=lambda t: (abs((t.date - out.date).days), t.id))
        money_in_by_amount[-out.amount_cents].remove(match)
        out.is_transfer = match.is_transfer = True
        out.transfer_pair_id, match.transfer_pair_id = match.id, out.id
