"""A small client for Plaid's API.

Plaid's API is plain JSON over HTTPS: every call is a POST with your client_id and secret in
the body. This file is the only place that talks to Plaid, so tests swap in a fake client
(see get_plaid) and never reach the internet.

Docs: https://plaid.com/docs/api/
"""

from typing import Any

import httpx2 as httpx

from app import config

HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidNotConfigured(Exception):
    """Plaid keys are missing from .env."""


class PlaidError(Exception):
    """Plaid answered with an error, e.g. ITEM_LOGIN_REQUIRED when a bank wants you to log in
    again. `code` is Plaid's error_code, for the app to react to."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class PlaidClient:
    def __init__(self, client_id: str, secret: str, environment: str):
        missing = [
            name
            for name, value in [
                ("PLAID_CLIENT_ID", client_id),
                (f"the {environment} secret (PLAID_SECRET_...)", secret),
            ]
            if not value
        ]
        if missing:
            raise PlaidNotConfigured(f"Plaid isn't set up: add {' and '.join(missing)} to .env")
        if environment not in HOSTS:
            raise PlaidNotConfigured(
                f"PLAID_ENV must be sandbox or production, not {environment!r}"
            )
        self.environment = environment
        self._auth = {"client_id": client_id, "secret": secret}
        self._http = httpx.Client(base_url=HOSTS[environment], timeout=30)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Call one Plaid endpoint, e.g. post("/item/get", {"access_token": ...})."""
        try:
            response = self._http.post(path, json={**self._auth, **body})
        except httpx.HTTPError as e:
            raise PlaidError("NETWORK_ERROR", f"couldn't reach Plaid: {e}") from e
        data = response.json()
        if response.status_code != 200:
            # Plaid's errors explain themselves; display_message is the friendlier one, when set.
            raise PlaidError(
                data.get("error_code", "UNKNOWN"),
                data.get("display_message") or data.get("error_message") or response.text,
            )
        return data


def get_plaid() -> PlaidClient:
    """FastAPI dependency: a client for the environment in .env (tests override this)."""
    return PlaidClient(config.PLAID_CLIENT_ID, config.PLAID_SECRET, config.PLAID_ENV)
