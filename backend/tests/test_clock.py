"""today() follows the TIMEZONE setting, not the server's clock."""

from app import config
from app.services.clock import today


def test_today_follows_the_timezone_setting(monkeypatch):
    # These two places are 25 hours apart, so they're never on the same date.
    monkeypatch.setattr(config, "TIMEZONE", "Pacific/Kiritimati")
    ahead = today()
    monkeypatch.setattr(config, "TIMEZONE", "Pacific/Pago_Pago")
    behind = today()
    assert (ahead - behind).days in (1, 2)
