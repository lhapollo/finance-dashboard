"""CIBC credit card CSV -> StandardTransaction.

What CIBC's export looks like (checked against a real download, Oct 2026):
- No header row. Five columns: date, description, debit, credit, masked card number.
- Dates are ISO: 2026-10-15.
- Purchases are a POSITIVE number in the debit column; payments, refunds and cashback are
  a positive number in the credit column. Exactly one of the two is filled in.
- Foreign purchases are already converted to CAD in the amount column; the description
  ends with the original amount, e.g. "MTA*NYCT PAYGO NEW YORK, NY 3.00 USD @ 1.393333".
- Rows are newest first.
"""

import csv
import re
from collections.abc import Iterable
from datetime import date

from pydantic import ValidationError

from app.importers.common import ImportFormatError, dollars_to_cents, title_case
from app.schemas import StandardTransaction


def parse_cibc(lines: Iterable[str]) -> list[StandardTransaction]:
    """Convert every row of a CIBC CSV. Raises ImportFormatError on the first bad row."""
    transactions = []
    for line_no, row in enumerate(csv.reader(lines), start=1):
        if not any(cell.strip() for cell in row):
            continue  # blank line
        if len(row) != 5:
            raise ImportFormatError(line_no, f"expected 5 columns, got {len(row)}")
        date_text, raw_description, debit, credit, _card = row

        try:
            txn_date = date.fromisoformat(date_text.strip())
        except ValueError:
            raise ImportFormatError(line_no, f"not a YYYY-MM-DD date: {date_text!r}") from None

        if debit.strip() and credit.strip():
            raise ImportFormatError(line_no, "both debit and credit are filled in")
        if not debit.strip() and not credit.strip():
            raise ImportFormatError(line_no, "neither debit nor credit is filled in")
        try:
            # Our rule: negative = money out. CIBC shows purchases as positive debits.
            amount_cents = -dollars_to_cents(debit) if debit.strip() else dollars_to_cents(credit)
        except ValueError as e:
            raise ImportFormatError(line_no, str(e)) from None

        try:
            transactions.append(
                StandardTransaction(
                    date=txn_date,
                    description=clean_description(raw_description),
                    raw_description=raw_description,
                    amount_cents=amount_cents,
                )
            )
        except ValidationError as e:
            raise ImportFormatError(line_no, e.errors()[0]["msg"]) from None
    return transactions


# --- Description cleanup -------------------------------------------------------------------
# Card descriptions are "<merchant> <city>, <province>". There's no separator between merchant
# and city, so cities with a space in them are listed here; otherwise the city is the last word.
_MULTI_WORD_CITIES = {
    "NORTH YORK",
    "RICHMOND HILL",
    "BLUE MOUNTAIN",
    "NEW YORK",
    "NEW JERSEY",
    "NIAGARA FALLS",
}
_FOREIGN_AMOUNT = re.compile(r"\s+\d*\.\d{2} [A-Z]{3} @ [\d.]+$")  # "3.00 USD @ 1.393333"
_PROVINCE = re.compile(r",\s*[A-Z]{2}$")  # ", ON"
_PROCESSOR_PREFIX = re.compile(r"^(SQ \*|TST-|WL \*|PAYPAL \*)\s*", re.IGNORECASE)
_STORE_NUMBER = re.compile(r"\s*#\s*\d+")  # "#40359"
_ORDER_CODE = re.compile(r"\s*[*/]\s*\S*\d\S*")  # "CA*531WG1200", "APPL/5GH8LFW8JV"
_TRAILING_JUNK = re.compile(
    r"(\s+(\d[\d-]{5,}|[A-Z0-9]*\d[A-Z0-9]{5,}|\d+))+$"  # phone numbers, reference codes
)


def clean_description(raw: str) -> str:
    """'MCDONALD'S #40359 NORTH YORK, ON' -> "Mcdonald's". Good enough, not perfect:
    raw_description keeps the original, so a bad cleanup never loses information."""
    text = " ".join(raw.split())
    text = _FOREIGN_AMOUNT.sub("", text)

    if _PROVINCE.search(text):
        text = _PROVINCE.sub("", text)
        for city in _MULTI_WORD_CITIES:
            if text.upper().endswith(" " + city):
                text = text[: -len(city) - 1]
                break
        else:
            text = text.rsplit(" ", 1)[0] if " " in text else text

    text = _PROCESSOR_PREFIX.sub("", text)
    text = _STORE_NUMBER.sub("", text)
    text = _ORDER_CODE.sub("", text)
    text = _TRAILING_JUNK.sub("", text)
    text = text.strip(" -*")

    return title_case(text) if text else title_case(raw)
