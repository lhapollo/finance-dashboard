"""Money as people read it, for messages. (The frontend formats everything else.)"""


def dollars(cents: int) -> str:
    """123456 -> "$1,234.56"; -500 -> "-$5.00". Integer math, so no rounding surprises."""
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{rest:02d}"
