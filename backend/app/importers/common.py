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


# --- Description cleanup -------------------------------------------------------------------
# Card descriptions are "<merchant> <city>, <province>" (converters reshape theirs to match).
# There's no separator between merchant and city, so cities with a space in them are listed
# here; otherwise the city is the last word.
_MULTI_WORD_CITIES = {
    "NORTH YORK",
    "RICHMOND HILL",
    "RICHMOND H",  # Tangerine cuts it off
    "BLUE MOUNTAIN",
    "NEW YORK",
    "NEW JERSEY",
    "NIAGARA FALLS",
}
_FOREIGN_AMOUNT = re.compile(r"\s+\d*\.\d{2} [A-Z]{3} @ [\d.]+$")  # "3.00 USD @ 1.393333"
_PROVINCE = re.compile(r",\s*[A-Z]{1,2}$")  # ", ON", or ", O" when a 32-character cut split it
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
    text = text.strip(" -*#")

    return title_case(text) if text else title_case(raw)
