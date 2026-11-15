"""Buckets, the fresh-start split, assigning and moving money."""

from datetime import date, timedelta

from sqlalchemy import select

from app.models import Allocation
from app.services.format import dollars


def make(client, name, type="recurring", **fields):
    response = client.post("/buckets", json={"name": name, "type": type, **fields})
    assert response.status_code == 201, response.text
    return next(b for b in response.json()["buckets"] if b["name"] == " ".join(name.split()))


def start(client, opening, day=None):
    return client.post(
        "/budget/start",
        json={
            "start_date": (day or date.today()).isoformat(),
            "opening": [{"bucket_id": b["id"], "amount_cents": c} for b, c in opening],
        },
    )


def balances(client):
    return {b["name"]: b["balance_cents"] for b in client.get("/budget").json()["buckets"]}


def test_dollars():
    assert dollars(123456) == "$1,234.56"
    assert dollars(-500) == "-$5.00"
    assert dollars(7) == "$0.07"


def test_before_setup(client, money):
    body = client.get("/budget").json()
    assert body["start_date"] is None
    assert body["available_cents"] == 280_000
    assert (body["assigned_cents"], body["unassigned_cents"]) == (0, 280_000)


def test_without_bank_balances_available_is_unknown(client):
    body = client.get("/budget").json()
    assert (body["available_cents"], body["unassigned_cents"]) == (None, None)


def test_goals_need_a_target_and_names_are_unique(client):
    assert client.post("/buckets", json={"name": "Switch 2", "type": "goal"}).status_code == 400
    make(client, "  Rent  ")
    assert client.post("/buckets", json={"name": "Rent", "type": "recurring"}).status_code == 409


def test_fresh_start_splits_available_money(client, money):
    rent, food = make(client, "Rent"), make(client, "Groceries")
    switch = make(client, "Switch 2", "goal", target_amount_cents=50_000)
    response = start(client, [(rent, 150_000), (food, 40_000), (switch, 18_000)])
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["start_date"] == date.today().isoformat()
    assert (body["assigned_cents"], body["unassigned_cents"]) == (208_000, 72_000)
    goal = next(b for b in body["buckets"] if b["name"] == "Switch 2")
    assert goal["progress_pct"] == 36  # $180 of $500


def test_opening_balances_never_exceed_available_money(client, money):
    rent = make(client, "Rent")
    response = start(client, [(rent, 280_001)])
    assert response.status_code == 400
    assert response.json()["detail"] == "that's $2,800.01, but you have $2,800.00 available"


def test_starting_needs_bank_balances(client):
    response = start(client, [(make(client, "Rent"), 100)])
    assert response.status_code == 400
    assert "connect a bank" in response.json()["detail"]


def test_starting_over_replaces_every_allocation(client, money, db_session):
    rent, food = make(client, "Rent"), make(client, "Groceries")
    start(client, [(rent, 100_000), (food, 50_000)])
    client.post(
        "/budget/move",
        json={"from_bucket_id": rent["id"], "to_bucket_id": food["id"], "amount_cents": 1_000},
    )
    start(client, [(rent, 20_000)])
    assert balances(client) == {"Rent": 20_000, "Groceries": 0}
    assert len(db_session.scalars(select(Allocation)).all()) == 1


def test_start_date_cant_be_in_the_future(client, money):
    response = start(client, [], day=date.today() + timedelta(days=1))
    assert response.status_code == 400


def test_assign_and_give_back(client, money):
    rent = make(client, "Rent")
    start(client, [(rent, 200_000)])  # $800 left unassigned

    body = client.post(
        "/budget/assign", json={"bucket_id": rent["id"], "amount_cents": 50_000}
    ).json()
    assert body["unassigned_cents"] == 30_000

    too_much = client.post("/budget/assign", json={"bucket_id": rent["id"], "amount_cents": 30_001})
    assert too_much.json()["detail"] == "only $300.00 is unassigned"

    back = client.post("/budget/assign", json={"bucket_id": rent["id"], "amount_cents": -250_001})
    assert back.json()["detail"] == "Rent only has $2,500.00"
    body = client.post(
        "/budget/assign", json={"bucket_id": rent["id"], "amount_cents": -5_000}
    ).json()
    assert body["unassigned_cents"] == 35_000


def test_assigning_needs_setup_first(client, money):
    rent = make(client, "Rent")
    response = client.post("/budget/assign", json={"bucket_id": rent["id"], "amount_cents": 100})
    assert response.json()["detail"] == "set up the budget first"


def test_move_money_keeps_unassigned_the_same(client, money):
    rent, food = make(client, "Rent"), make(client, "Groceries")
    start(client, [(rent, 100_000), (food, 10_000)])
    before = client.get("/budget").json()["unassigned_cents"]

    move = {"from_bucket_id": rent["id"], "to_bucket_id": food["id"], "amount_cents": 2_500}
    body = client.post("/budget/move", json=move).json()
    assert body["unassigned_cents"] == before
    assert balances(client) == {"Rent": 97_500, "Groceries": 12_500}

    move["amount_cents"] = 100_000
    assert client.post("/budget/move", json=move).json()["detail"] == "Rent only has $975.00"
    move["to_bucket_id"] = rent["id"]
    assert client.post("/budget/move", json=move).status_code == 400


def test_archiving_returns_the_leftover_to_unassigned(client, money):
    switch = make(client, "Switch 2", "goal", target_amount_cents=50_000)
    start(client, [(switch, 30_000)])
    body = client.patch(f"/buckets/{switch['id']}", json={"archived": True}).json()
    assert body["unassigned_cents"] == 280_000
    archived = body["buckets"][-1]
    assert (archived["archived"], archived["balance_cents"]) == (True, 0)

    put_in = {"bucket_id": switch["id"], "amount_cents": 100}
    assert client.post("/budget/assign", json=put_in).json()["detail"] == "Switch 2 is archived"


def test_rename_and_change_target(client):
    switch = make(client, "Switch", "goal", target_amount_cents=50_000)
    body = client.patch(
        f"/buckets/{switch['id']}",
        json={"name": "Switch 2", "target_amount_cents": 60_000, "target_date": "2026-12-20"},
    ).json()
    [b] = body["buckets"]
    assert (b["name"], b["target_amount_cents"], b["target_date"]) == (
        "Switch 2",
        60_000,
        "2026-12-20",
    )
    no_target = client.patch(f"/buckets/{switch['id']}", json={"target_amount_cents": None})
    assert no_target.status_code == 400


def test_delete_only_buckets_without_history(client, money):
    oops, rent = make(client, "Oops"), make(client, "Rent")
    assert client.delete(f"/buckets/{oops['id']}").status_code == 204
    start(client, [(rent, 100)])
    response = client.delete(f"/buckets/{rent['id']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "Rent has history; archive it instead"
