"""Buckets, the fresh-start split, assigning and moving money."""

from datetime import timedelta

from sqlalchemy import select

from app.models import Account, Allocation
from app.services.clock import today
from app.services.format import dollars


def make(client, name, type="recurring", **fields):
    response = client.post("/buckets", json={"name": name, "type": type, **fields})
    assert response.status_code == 201, response.text
    return next(b for b in response.json()["buckets"] if b["name"] == " ".join(name.split()))


def start(client, opening, day=None):
    return client.post(
        "/budget/start",
        json={
            "start_date": (day or today()).isoformat(),
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
    assert body["start_date"] == today().isoformat()
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
    response = start(client, [], day=today() + timedelta(days=1))
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


def test_pending_transactions_count_in_available_money(client, money, db_session, chequing, add):
    """Banks leave pending transactions out of the balance they report; buckets don't."""
    card = db_session.scalar(select(Account).where(Account.name == "Tangerine Mastercard"))
    before = client.get("/budget").json()["available_cents"]  # $200 owed on the card

    add(card, 14, -2_000, "PENDING DINNER", pending=True)
    # Paying the card off: already gone from chequing (and its balance), pending on the card.
    add(chequing, 13, -20_000, "Tangerine Credit Card Payment", is_transfer=True)
    chequing.balance_cents -= 20_000
    add(card, 13, 20_000, "PAYMENT - THANK YOU", is_transfer=True, pending=True)

    balances = client.get("/summary/balances").json()
    assert balances["owed_cents"] == 2_000  # paid off; just the pending dinner
    assert client.get("/budget").json()["available_cents"] == before - 2_000


def test_money_im_owed_counts_as_mine(client, money, db_session, chequing, add):
    """Paying for someone takes the money out of my account, but it's still mine: marking it
    reimbursable refills its bucket without making unassigned go negative, and the payback
    moves it from "owed" to "available"."""
    mastercard = db_session.scalar(select(Account).where(Account.name == "Tangerine Mastercard"))
    dining = make(client, "Dining")
    assert start(client, [(dining, 50_000)]).status_code == 200
    assert client.get("/budget").json()["unassigned_cents"] == 230_000

    dinner = add(mastercard, today(), -3_000, "BAR RAVAL", category="dining")
    mastercard.balance_cents -= 3_000  # the bank's balance has it
    db_session.flush()
    assert balances(client)["Dining"] == 47_000
    assert client.get("/budget").json()["unassigned_cents"] == 230_000

    client.patch(f"/transactions/{dinner.id}", json={"reimbursable": True})
    body = client.get("/budget").json()
    assert balances(client)["Dining"] == 50_000
    assert (body["available_cents"], body["owed_to_me_cents"], body["owed_to_me_count"]) == (
        277_000,
        3_000,
        1,
    )
    assert body["unassigned_cents"] == 230_000

    payback = add(chequing, today(), 3_000, "E-TRANSFER FROM SAM")
    chequing.balance_cents += 3_000
    db_session.flush()
    client.patch(f"/transactions/{payback.id}", json={"reimburses_id": dinner.id})
    body = client.get("/budget").json()
    assert (body["available_cents"], body["owed_to_me_cents"]) == (280_000, 0)
    assert body["unassigned_cents"] == 230_000


def test_owed_money_only_counts_from_accounts_with_a_balance(client, money, card, add):
    """CIBC has no bank balance, so its purchases never lowered available money; what I'm owed
    for them can't raise it either."""
    dinner = add(card, today(), -3_000, "BAR RAVAL", category="dining")
    client.patch(f"/transactions/{dinner.id}", json={"reimbursable": True})

    body = client.get("/budget").json()
    assert body["owed_to_me_cents"] == 0
    assert client.get("/summary/reimbursements").json()["waiting_cents"] == 3_000  # still owed


def test_the_fresh_start_can_split_money_im_owed(client, money, db_session, add):
    mastercard = db_session.scalar(select(Account).where(Account.name == "Tangerine Mastercard"))
    dinner = add(mastercard, 1, -3_000, "BAR RAVAL", reimbursable=True)
    mastercard.balance_cents -= 3_000
    rent = make(client, "Rent")

    response = start(client, [(rent, 280_001)])
    assert response.json()["detail"] == (
        "that's $2,800.01, but you have $2,800.00 available (including $30.00 you're owed)"
    )
    assert start(client, [(rent, 280_000)]).status_code == 200
    assert dinner.reimbursable
