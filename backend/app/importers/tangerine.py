"""Tangerine chequing CSV -> StandardTransaction.

What Tangerine's export looks like (checked against a real download, Oct 2026):
- A header row: Date,Transaction,Name,Memo,Amount.
- Dates are MM/DD/YYYY (month first: rows like 10/15/2023 rule out day first).
- Amount is already signed our way: negative = money out.
- Name is Memo cut off at 32 characters, so Memo is the description we keep.
- Some rows are notes with a 0.00 amount ("Posted :26 Nov 2023", a zero "Interest Paid").
  They aren't transactions, so they're skipped.
- Rows are oldest first, but not strictly (a reversal can appear after later rows).
"""

import csv
import re
from collections.abc import Iterable
from datetime import datetime

from pydantic import ValidationError

from app.importers.common import ImportFormatError, clean_description, dollars_to_cents, title_case
from app.schemas import StandardTransaction

HEADER = ["Date", "Transaction", "Name", "Memo", "Amount"]


def parse_tangerine(lines: Iterable[str]) -> list[StandardTransaction]:
    """Convert every row of a Tangerine CSV. Raises ImportFormatError on the first bad row."""
    transactions = []
    rows = enumerate(csv.reader(lines), start=1)
    for line_no, row in rows:
        if line_no == 1:
            if [cell.strip() for cell in row] != HEADER:
                raise ImportFormatError(1, f"expected the header {','.join(HEADER)}")
            continue
        if not any(cell.strip() for cell in row):
            continue  # blank line
        if len(row) != 5:
            raise ImportFormatError(line_no, f"expected 5 columns, got {len(row)}")
        date_text, _type, name, memo, amount_text = row

        try:
            txn_date = datetime.strptime(date_text.strip(), "%m/%d/%Y").date()
        except ValueError:
            raise ImportFormatError(line_no, f"not a MM/DD/YYYY date: {date_text!r}") from None
        try:
            amount_cents = signed_cents(amount_text)
        except ValueError as e:
            raise ImportFormatError(line_no, str(e)) from None
        if amount_cents == 0:
            continue  # a note, not a transaction

        # Kept exactly as written: its double spaces are what separate merchant and province.
        raw_description = (memo or name).strip()
        try:
            transactions.append(
                StandardTransaction(
                    date=txn_date,
                    description=clean_tangerine(raw_description),
                    raw_description=raw_description,
                    amount_cents=amount_cents,
                )
            )
        except ValidationError as e:
            raise ImportFormatError(line_no, e.errors()[0]["msg"]) from None
    return transactions


def signed_cents(text: str) -> int:
    """'-30.00' -> -3000, '35.00' -> 3500."""
    text = text.strip()
    if text.startswith("-"):
        return -dollars_to_cents(text[1:])
    return dollars_to_cents(text)


# --- Description cleanup -------------------------------------------------------------------
# Purchases: "Interac - Purchase - PHO ANH VU WATE WATERLOO  ON  CA" (two spaces before the
# province and country). Reshaped to "PHO ANH VU WATE WATERLOO, ON", the card layout that
# clean_description already knows how to tidy.
_PURCHASE = re.compile(r"^(?:Interac|Visa Debit) - (?:Purchase|Refund) - (?P<rest>.+)$", re.I)
_PLACE = re.compile(r"\s{2,}(?:(?P<province>[A-Z]{2})\s{2,})?CA$")
_E_TRANSFER = re.compile(
    r"^(?P<cancelled>Cancelled )?INTERAC e-Transfer (?P<direction>To|From):\s*(?P<who>.+)$", re.I
)
_OWN_TANGERINE = re.compile(
    r"^(?P<recurring>Recurring )?Internet (?P<direction>Deposit from|Withdrawal to) "
    r"Tangerine (?P<account>\w+) Account",
    re.I,
)
_EFT = re.compile(r"^EFT (?P<kind>Deposit|Withdrawal)(?P<extra>.*?) (?:from|to) (?P<who>.+)$", re.I)
_ACCOUNT_NUMBER = re.compile(r"\s+-\s+[*\d]+$")  # "Bill Payment - CIBC VISA - ****4362"


def clean_tangerine(raw: str) -> str:
    if m := _PURCHASE.match(raw):
        rest = m["rest"]
        if place := _PLACE.search(rest):
            rest = f"{rest[: place.start()]}, {place['province'] or 'CA'}"
        return clean_description(rest)
    if m := _E_TRANSFER.match(raw):
        prefix = "Cancelled e-Transfer" if m["cancelled"] else "e-Transfer"
        return f"{prefix} {m['direction'].lower()} {title_case(m['who'])}"
    if m := _OWN_TANGERINE.match(raw):
        direction = "from" if m["direction"].lower().startswith("deposit") else "to"
        recurring = "Recurring transfer" if m["recurring"] else "Transfer"
        return f"{recurring} {direction} Tangerine {m['account'].title()}"
    if m := _EFT.match(raw):
        # Deposits are named after who paid ("Rippling Canada"); withdrawals after the payee.
        who = title_case(m["who"])
        return who if m["kind"].lower() == "deposit" else f"Payment to {who}"
    return title_case(_ACCOUNT_NUMBER.sub("", raw))
