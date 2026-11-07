"""Tangerine CSVs -> StandardTransaction: chequing, savings and the Mastercard.

All three exports (checked against real downloads, Oct/Nov 2026) share a shape:
- A header row, then Transaction type, Name, Memo and Amount columns.
- Dates are MM/DD/YYYY (month first: rows like 10/15/2023 rule out day first).
- Amount is already signed our way: negative = money out.

Where they differ:
- Chequing: the header starts "Date". Name is Memo cut off at 32 characters, so Memo is the
  description we keep. Some rows are notes with a 0.00 amount ("Posted :26 Nov 2023", a zero
  "Interest Paid"); they aren't transactions, so they're skipped. Rows are oldest first.
- Savings: exactly the chequing layout, header included, so the header can't tell them apart.
  Instead, a transfer row names the *other* account ("Internet Withdrawal to Tangerine
  Chequing Account"), and no account transfers to itself: a chequing file that mentions
  "Tangerine Chequing Account" is really a savings file, and the other way round.
- Mastercard: the header starts "Transaction date". Name is the merchant and place, cut off at
  32 characters ("SANSOTEI RAMEN ADELAID TORONTO O"); Memo is rewards info ("Rewards earned:
  0.52 ~ Category: Restaurant"), so Name is the description we keep. Newest first, and each
  statement period downloads as its own file.
"""

import csv
import re
from collections.abc import Callable, Iterable
from datetime import datetime

from pydantic import ValidationError

from app.importers.common import ImportFormatError, clean_description, dollars_to_cents, title_case
from app.schemas import StandardTransaction

CHEQUING_HEADER = ["Date", "Transaction", "Name", "Memo", "Amount"]
CARD_HEADER = ["Transaction date", "Transaction", "Name", "Memo", "Amount"]


def parse_tangerine(lines: Iterable[str]) -> list[StandardTransaction]:
    """Tangerine chequing. Raises ImportFormatError on the first bad row."""
    return _parse_bank_account(lines, "Chequing")


def parse_tangerine_savings(lines: Iterable[str]) -> list[StandardTransaction]:
    """Tangerine savings. Raises ImportFormatError on the first bad row."""
    return _parse_bank_account(lines, "Savings")


def _parse_bank_account(lines: Iterable[str], account: str) -> list[StandardTransaction]:
    # Memo kept exactly as written: its double spaces separate merchant and province.
    return _parse(
        lines,
        CHEQUING_HEADER,
        lambda name, memo: (memo or name).strip(),
        clean_tangerine,
        this_account=account,
    )


def parse_tangerine_card(lines: Iterable[str]) -> list[StandardTransaction]:
    """Tangerine Mastercard. Raises ImportFormatError on the first bad row."""
    return _parse(lines, CARD_HEADER, lambda name, memo: name.strip(), clean_tangerine_card)


def _parse(
    lines: Iterable[str],
    header: list[str],
    pick_raw: Callable[[str, str], str],
    clean: Callable[[str], str],
    this_account: str | None = None,
) -> list[StandardTransaction]:
    transactions = []
    for line_no, row in enumerate(csv.reader(lines), start=1):
        if line_no == 1:
            if [cell.strip() for cell in row] != header:
                raise ImportFormatError(1, f"expected the header {','.join(header)}")
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

        raw_description = pick_raw(name, memo)
        if this_account and _transfers_with_itself(raw_description, this_account):
            other = "Savings" if this_account == "Chequing" else "Chequing"
            raise ImportFormatError(
                line_no,
                f"this row moves money to or from Tangerine {this_account} itself, so the file "
                f"looks like a {other.lower()} export; upload it to Tangerine {other}",
            )
        try:
            transactions.append(
                StandardTransaction(
                    date=txn_date,
                    description=clean(raw_description),
                    raw_description=raw_description,
                    amount_cents=amount_cents,
                )
            )
        except ValidationError as e:
            raise ImportFormatError(line_no, e.errors()[0]["msg"]) from None
    return transactions


def _transfers_with_itself(raw: str, account: str) -> bool:
    m = _OWN_TANGERINE.match(raw)
    return m is not None and m["account"].lower() == account.lower()


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


# Mastercard names end "<city> <province>" with no comma, and the 32-character cut can leave
# the province as one letter ("TORONTO O") or remove it ("NORTH YOR").
_CARD_PROVINCE = re.compile(r" (?P<province>[A-Z]{1,2})$")


def clean_tangerine_card(raw: str) -> str:
    """'SANSOTEI RAMEN ADELAID TORONTO O' -> 'Sansotei Ramen Adelaid'."""
    text = " ".join(raw.split())
    if m := _CARD_PROVINCE.search(text):
        text = f"{text[: m.start()]}, {m['province']}"
    return clean_description(text)
