"""The Plaid converter: one Plaid transaction -> the standard format, like the CSV converters.

Checked against real Tangerine data from Plaid, compared with the same transactions from CSVs:
- Amounts: Plaid uses positive for money OUT, the opposite of our rule, so the sign flips.
- Dates: for credit cards Plaid's `date` is when the purchase posted, 0 to 4 days after the
  purchase date the card's CSV shows. That's `authorized_date`, so cards use it. Bank
  accounts' `date` already matches their CSVs.
- Descriptions: `original_description` is the bank's own wording, the same text as the CSV
  (sometimes a few characters longer, where the CSV cut it off). So each bank's CSV cleanup,
  category rules and transfer rules work on it unchanged. Except: Tangerine debit purchases
  can end in "Posted :08 Nov 2026", which the CSVs never have, so that's dropped.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.importers.common import clean_description
from app.importers.tangerine import clean_tangerine, clean_tangerine_card
from app.models import Account
from app.schemas import StandardTransaction

_POSTED_SUFFIX = re.compile(r"\s+Posted\s*:\s*\d{1,2} [A-Za-z]{3} \d{4}$")

# Each bank's description cleanup, as its CSV converter does it.
CLEANERS = {
    ("Tangerine", "credit"): clean_tangerine_card,
    ("Tangerine", "chequing"): clean_tangerine,
    ("Tangerine", "savings"): clean_tangerine,
}


@dataclass(frozen=True)
class PlaidTransaction:
    """The standard transaction, plus what Plaid needs to update it later."""

    transaction: StandardTransaction
    plaid_transaction_id: str
    pending: bool
    # On a posted transaction: the pending one it replaces, if we saw that one first.
    pending_transaction_id: str | None


def convert_plaid(t: dict[str, Any], account: Account) -> PlaidTransaction:
    raw = " ".join((t.get("original_description") or t["name"]).split())
    raw = _POSTED_SUFFIX.sub("", raw)[:500]
    clean = CLEANERS.get((account.institution, account.type), clean_description)
    day = (account.type == "credit" and t.get("authorized_date")) or t["date"]
    return PlaidTransaction(
        transaction=StandardTransaction(
            date=date.fromisoformat(day),
            description=clean(raw)[:500] or raw,
            raw_description=raw,
            # Through str, so 12.1 becomes exactly 1210 cents, never 1209.9999.
            amount_cents=-int((Decimal(str(t["amount"])) * 100).quantize(Decimal(1))),
            source="plaid",
        ),
        plaid_transaction_id=t["transaction_id"],
        pending=bool(t.get("pending")),
        pending_transaction_id=t.get("pending_transaction_id"),
    )
