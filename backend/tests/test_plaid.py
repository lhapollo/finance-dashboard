"""Connecting banks through Plaid. A fake Plaid stands in for the real one, so these tests
never reach the internet and need no keys."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app import config
from app.main import app
from app.models import PlaidItem
from app.plaid import PlaidClient, PlaidError, PlaidNotConfigured, get_plaid
from app.routers import plaid as plaid_router
from app.services.secrets import TokenKeyError, decrypt_token, encrypt_token


class FakePlaid:
    """Records calls and answers like Plaid's sandbox would."""

    environment = "sandbox"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail_with: PlaidError | None = None

    def post(self, path, body):
        self.calls.append((path, body))
        if self.fail_with:
            raise self.fail_with
        if path == "/link/token/create":
            return {"link_token": "link-sandbox-123"}
        if path == "/item/public_token/exchange":
            return {"access_token": "access-sandbox-secret", "item_id": "item-abc"}
        if path == "/item/remove":
            return {}
        raise AssertionError(f"unexpected call to {path}")


@pytest.fixture(autouse=True)
def token_key(monkeypatch):
    monkeypatch.setattr(config, "PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "PLAID_ENV", "sandbox")


@pytest.fixture
def fake_plaid(monkeypatch):
    fake = FakePlaid()
    app.dependency_overrides[get_plaid] = lambda: fake
    monkeypatch.setattr(plaid_router, "get_plaid", lambda: fake)
    return fake


def connect(client, name="Tangerine"):
    return client.post(
        "/plaid/items", json={"public_token": "public-sandbox-1", "institution_name": name}
    )


# --- encryption ---


def test_tokens_round_trip_and_are_unreadable_when_saved():
    saved = encrypt_token("access-sandbox-secret")
    assert "access-sandbox-secret" not in saved
    assert decrypt_token(saved) == "access-sandbox-secret"


def test_a_different_key_cant_decrypt(monkeypatch):
    saved = encrypt_token("access-sandbox-secret")
    monkeypatch.setattr(config, "PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    with pytest.raises(TokenKeyError, match="changed"):
        decrypt_token(saved)


def test_missing_key_is_explained(monkeypatch):
    monkeypatch.setattr(config, "PLAID_TOKEN_KEY", "")
    with pytest.raises(TokenKeyError, match="isn't set"):
        encrypt_token("x")


# --- the client ---


def test_client_names_missing_keys():
    with pytest.raises(PlaidNotConfigured, match="PLAID_CLIENT_ID"):
        PlaidClient("", "secret", "sandbox")
    with pytest.raises(PlaidNotConfigured, match="sandbox secret"):
        PlaidClient("id", "", "sandbox")
    with pytest.raises(PlaidNotConfigured, match="PLAID_ENV"):
        PlaidClient("id", "secret", "development")


# --- endpoints ---


def test_status_explains_what_is_missing(client, monkeypatch):
    monkeypatch.setattr(config, "PLAID_CLIENT_ID", "")
    body = client.get("/plaid/status").json()
    assert body["configured"] is False
    assert "PLAID_CLIENT_ID" in body["problem"]


def test_link_token(client, fake_plaid):
    response = client.post("/plaid/link-token")
    assert response.status_code == 200
    assert response.json() == {"link_token": "link-sandbox-123"}
    path, body = fake_plaid.calls[0]
    assert path == "/link/token/create"
    assert body["country_codes"] == ["CA"]
    assert body["products"] == ["transactions"]


def test_connecting_saves_the_token_encrypted_and_never_returns_it(client, db_session, fake_plaid):
    response = connect(client)
    assert response.status_code == 201
    assert "access" not in response.text  # neither the token nor a field for it
    assert response.json()["institution_name"] == "Tangerine"

    item = db_session.scalar(select(PlaidItem))
    assert item.item_id == "item-abc"
    assert item.environment == "sandbox"
    assert item.access_token != "access-sandbox-secret"
    assert decrypt_token(item.access_token) == "access-sandbox-secret"

    listed = client.get("/plaid/items")
    assert [i["institution_name"] for i in listed.json()] == ["Tangerine"]
    assert "access" not in listed.text


def test_connect_without_a_key_does_nothing_at_plaid(client, fake_plaid, monkeypatch):
    monkeypatch.setattr(config, "PLAID_TOKEN_KEY", "")
    response = connect(client)
    assert response.status_code == 503
    assert "PLAID_TOKEN_KEY" in response.json()["detail"]
    assert fake_plaid.calls == []  # no login created at Plaid that we couldn't save


def test_plaid_errors_become_readable_messages(client, fake_plaid):
    fake_plaid.fail_with = PlaidError("INVALID_PUBLIC_TOKEN", "the public token is expired")
    response = connect(client)
    assert response.status_code == 502
    assert response.json()["detail"] == "Plaid: the public token is expired (INVALID_PUBLIC_TOKEN)"


def test_removing_a_bank_deletes_it_at_plaid_too(client, db_session, fake_plaid):
    item_id = connect(client).json()["id"]
    assert client.delete(f"/plaid/items/{item_id}").status_code == 204
    assert fake_plaid.calls[-1] == ("/item/remove", {"access_token": "access-sandbox-secret"})
    assert db_session.scalar(select(PlaidItem)) is None


def test_removing_a_bank_already_gone_at_plaid(client, db_session, fake_plaid):
    item_id = connect(client).json()["id"]
    fake_plaid.fail_with = PlaidError("ITEM_NOT_FOUND", "not found")
    assert client.delete(f"/plaid/items/{item_id}").status_code == 204
    assert db_session.scalar(select(PlaidItem)) is None


def test_removing_keeps_the_bank_when_plaid_fails(client, db_session, fake_plaid):
    item_id = connect(client).json()["id"]
    fake_plaid.fail_with = PlaidError("INTERNAL_SERVER_ERROR", "try again")
    assert client.delete(f"/plaid/items/{item_id}").status_code == 502
    assert db_session.scalar(select(PlaidItem)) is not None


def test_removing_after_the_key_changed(client, db_session, fake_plaid, monkeypatch):
    item_id = connect(client).json()["id"]
    monkeypatch.setattr(config, "PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    assert client.delete(f"/plaid/items/{item_id}").status_code == 204
    assert fake_plaid.calls[-1][0] != "/item/remove"  # the token was unreadable
    assert db_session.scalar(select(PlaidItem)) is None


def test_a_production_bank_cant_be_removed_from_sandbox(client, db_session, fake_plaid):
    item_id = connect(client).json()["id"]
    db_session.get(PlaidItem, item_id).environment = "production"
    response = client.delete(f"/plaid/items/{item_id}")
    assert response.status_code == 409
    assert "PLAID_ENV=production" in response.json()["detail"]


def test_sandbox_banks_are_forgotten_in_production(client, db_session, fake_plaid, monkeypatch):
    item_id = connect(client).json()["id"]
    monkeypatch.setattr(config, "PLAID_ENV", "production")
    assert client.delete(f"/plaid/items/{item_id}").status_code == 204
    assert fake_plaid.calls[-1][0] != "/item/remove"
    assert db_session.scalar(select(PlaidItem)) is None
