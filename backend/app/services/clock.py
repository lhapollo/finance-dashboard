"""Today's date where I live, not on the server.

Docker containers run in UTC, so at 9 p.m. in Toronto the server's date.today() is already
tomorrow. Everything that asks "what day is it?" goes through here instead.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import config


def today() -> date:
    return datetime.now(ZoneInfo(config.TIMEZONE)).date()
