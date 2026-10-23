from collections.abc import Callable, Iterable

from app.importers.cibc import parse_cibc
from app.schemas import StandardTransaction

Converter = Callable[[Iterable[str]], list[StandardTransaction]]

# Which converter reads which account's CSVs, keyed by (institution, account type).
CONVERTERS: dict[tuple[str, str], Converter] = {
    ("CIBC", "credit"): parse_cibc,
}
