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
from collections.abc import Iterable
from datetime import date

from pydantic import ValidationError

from app.importers.common import ImportFormatError, clean_description, dollars_to_cents
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
