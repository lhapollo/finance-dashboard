"""Fingerprints: the ID that lets an overlapping CSV re-import skip rows it already has."""

import hashlib
from collections import Counter

from app.schemas import StandardTransaction


def fingerprints(account_id: int, transactions: list[StandardTransaction]) -> list[str]:
    """One fingerprint per transaction, in the same order.

    Date + amount + description alone isn't unique: four $4.18 subway taps on the same day
    are four real rows with identical text. So each fingerprint also includes which copy
    it is (1st, 2nd, ...) within this file. Re-importing an overlapping file gives the same
    copies the same numbers, so they're still skipped, as long as the file covers whole days
    (bank exports do).

    Uses raw_description, not the cleaned one, so improving the cleanup later doesn't make
    old rows look new.
    """
    seen: Counter[tuple] = Counter()
    result = []
    for t in transactions:
        key = (account_id, t.date.isoformat(), t.amount_cents, t.raw_description)
        seen[key] += 1
        text = "|".join(str(part) for part in (*key, seen[key]))
        result.append(hashlib.sha256(text.encode()).hexdigest())
    return result
