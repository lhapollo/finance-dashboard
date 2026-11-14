"""Encrypting Plaid access tokens before they're saved.

An access token works like a password for reading one bank login's data, so the database
only ever holds it encrypted. The key lives in .env (PLAID_TOKEN_KEY), never in the database,
so a copy of the database alone can't be used to read your banks.

Fernet (from the `cryptography` library) is "symmetric" encryption: the same key locks and
unlocks. It also detects tampering: decrypting anything that was changed raises an error.
"""

from cryptography.fernet import Fernet, InvalidToken

from app import config


class TokenKeyError(Exception):
    """PLAID_TOKEN_KEY is missing, malformed, or isn't the key a token was encrypted with."""


def _fernet() -> Fernet:
    if not config.PLAID_TOKEN_KEY:
        raise TokenKeyError("PLAID_TOKEN_KEY isn't set in .env (see .env.example)")
    try:
        return Fernet(config.PLAID_TOKEN_KEY)
    except ValueError as e:
        raise TokenKeyError("PLAID_TOKEN_KEY in .env isn't a valid key") from e


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as e:
        raise TokenKeyError(
            "can't decrypt a saved Plaid token: PLAID_TOKEN_KEY changed since it was saved. "
            "Remove the bank and connect it again."
        ) from e


def require_token_key() -> None:
    """Raise TokenKeyError now if the key is missing or malformed."""
    _fernet()
