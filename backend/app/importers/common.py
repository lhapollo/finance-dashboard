"""Helpers shared by every bank converter."""

import re
from decimal import Decimal, InvalidOperation


class ImportFormatError(ValueError):
    """A row didn't look the way this converter expects. Raised so a format change fails loudly."""

    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line


_MONEY = re.compile(r"^\d*\.?\d{0,2}$")


def dollars_to_cents(text: str) -> int:
    """'46.18' -> 4618, '.80' -> 80, '1,199.94' -> 119994. Rejects fractions of a cent.

    Goes through Decimal, never float: float('46.18') * 100 is 4617.999999999999.
    """
    cleaned = text.strip().replace(",", "").replace("$", "")
    if not cleaned or not _MONEY.match(cleaned) or cleaned == ".":
        raise ValueError(f"not a dollar amount: {text!r}")
    try:
        return int(Decimal(cleaned) * 100)
    except InvalidOperation as e:
        raise ValueError(f"not a dollar amount: {text!r}") from e


_SMALL_WORDS = {"of", "and", "the", "at", "on", "in", "for", "de", "du", "la", "le"}


_WORD_START = re.compile(r"(^|[-/&])([a-z])")


def title_case(text: str) -> str:
    """'UNIVERSITY OF WATERLOO' -> 'University of Waterloo', 'WAL-MART' -> 'Wal-Mart',
    "MCDONALD'S" -> "Mcdonald's" (an apostrophe doesn't start a new word)."""
    words = text.lower().split()
    return " ".join(
        w if i > 0 and w in _SMALL_WORDS else _WORD_START.sub(lambda m: m[1] + m[2].upper(), w)
        for i, w in enumerate(words)
    )
