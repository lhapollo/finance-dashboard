"""Closing and reopening accounts."""

from datetime import date


def test_close_and_reopen(client, card):
    response = client.patch(f"/accounts/{card.id}", json={"closed_on": "2026-11-20"})
    assert response.status_code == 200
    assert response.json()["closed_on"] == "2026-11-20"
    assert card.closed_on == date(2026, 11, 20)

    # Closed accounts are listed last, everywhere accounts are listed.
    assert client.get("/accounts").json()[-1]["id"] == card.id
    activity = client.get("/summary/accounts?month=2026-11").json()
    assert activity[-1]["id"] == card.id and activity[-1]["closed_on"] == "2026-11-20"

    assert client.patch(f"/accounts/{card.id}", json={"closed_on": None}).status_code == 200
    assert card.closed_on is None


def test_leaving_closed_on_out_changes_nothing(client, card):
    client.patch(f"/accounts/{card.id}", json={"closed_on": "2026-11-20"})
    assert client.patch(f"/accounts/{card.id}", json={}).json()["closed_on"] == "2026-11-20"


def test_unknown_account(client):
    assert client.patch("/accounts/9999", json={"closed_on": None}).status_code == 404
