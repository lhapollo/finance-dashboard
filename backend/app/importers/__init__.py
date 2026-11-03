from collections.abc import Callable, Iterable

from app.importers.cibc import parse_cibc
from app.importers.tangerine import parse_tangerine, parse_tangerine_card
from app.schemas import StandardTransaction

Converter = Callable[[Iterable[str]], list[StandardTransaction]]

# Which converter reads which account's CSVs, keyed by (institution, account type).
CONVERTERS: dict[tuple[str, str], Converter] = {
    ("CIBC", "credit"): parse_cibc,
    ("Tangerine", "chequing"): parse_tangerine,
    ("Tangerine", "credit"): parse_tangerine_card,
}
