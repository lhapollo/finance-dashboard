"""Spending out of buckets: category defaults, picking a bucket by hand, and what counts."""

from datetime import date

import pytest

START = date(2026, 10, 10)  # the budget starts here; `add` puts rows in October 2026


@pytest.fixture
def buckets(client, money):
    """Food ($400) and Fun ($100), budgeting since Oct 10. Groceries and dining come out of
    Food by default; nothing defaults to Fun."""
    made = {}
    for name in ["Food", "Fun"]:
        response = client.post("/buckets", json={"name": name, "type": "recurring"})
        made[name] = next(b["id"] for b in response.json()["buckets"] if b["name"] == name)
    response = client.post(
        "/budget/start",
        json={
            "start_date": START.isoformat(),
            "opening": [
                {"bucket_id": made["Food"], "amount_cents": 40_000},
                {"bucket_id": made["Fun"], "amount_cents": 10_000},
            ],
        },
    )
    assert response.status_code == 200, response.text
    for category in ["groceries", "dining"]:
        client.put(f"/budget/categories/{category}", json={"bucket_id": made["Food"]})
    return made


def state(client):
    body = client.get("/budget").json()
    by_name = {b["name"]: (b["spent_cents"], b["balance_cents"]) for b in body["buckets"]}
    return by_name, body["unbucketed_spent_cents"]


def test_spending_comes_out_of_the_categorys_bucket(client, buckets, chequing, add):
    add(chequing, 12, -5_000, category="groceries")
    add(chequing, 13, -2_500, category="dining")
    add(chequing, 14, -1_000, category="shopping")  # no bucket for shopping
    by_name, unbucketed = state(client)
    assert by_name == {"Food": (7_500, 32_500), "Fun": (0, 10_000)}
    assert unbucketed == 1_000


def test_spending_before_the_start_doesnt_count(client, buckets, chequing, add):
    add(chequing, 9, -5_000, category="groceries")  # the day before the start
    add(chequing, 10, -100, category="groceries")
    assert state(client)[0]["Food"] == (100, 39_900)


def test_refunds_put_money_back(client, buckets, chequing, add):
    add(chequing, 12, -5_000, category="groceries")
    add(chequing, 15, 1_200, category="groceries")  # returned something
    assert state(client)[0]["Food"] == (3_800, 36_200)


def test_transfers_income_and_reimbursable_dont_count(client, buckets, chequing, add):
    add(chequing, 12, -5_000, category="groceries", is_transfer=True)
    add(chequing, 12, -5_000, category="groceries", reimbursable=True)
    add(chequing, 12, 300_000, category="income")
    assert state(client) == ({"Food": (0, 40_000), "Fun": (0, 10_000)}, 0)


def test_overspending_goes_negative(client, buckets, chequing, add):
    add(chequing, 12, -45_000, category="groceries")
    assert state(client)[0]["Food"] == (45_000, -5_000)
    # An overspent bucket has nothing to move out.
    move = {"from_bucket_id": buckets["Food"], "to_bucket_id": buckets["Fun"], "amount_cents": 1}
    assert client.post("/budget/move", json=move).json()["detail"] == "Food only has $0.00"
    # Covering it: move money in from another bucket.
    move = {
        "from_bucket_id": buckets["Fun"],
        "to_bucket_id": buckets["Food"],
        "amount_cents": 5_000,
    }
    assert client.post("/budget/move", json=move).status_code == 200
    assert state(client)[0]["Food"] == (45_000, 0)


def test_picking_a_bucket_by_hand_wins(client, buckets, chequing, add):
    concert = add(chequing, 12, -6_000, category="dining")  # dinner at a concert venue
    snack = add(chequing, 12, -500, category="groceries")
    client.patch(f"/transactions/{concert.id}", json={"bucket_id": buckets["Fun"]})
    client.patch(f"/transactions/{snack.id}", json={"bucket_id": None})  # no bucket
    by_name, unbucketed = state(client)
    assert by_name == {"Food": (0, 40_000), "Fun": (6_000, 4_000)}
    assert unbucketed == 500

    body = client.patch(f"/transactions/{concert.id}", json={"bucket_auto": True}).json()
    assert (body["bucket_id"], body["bucket_assigned_by"]) == (None, None)
    assert state(client)[0]["Food"] == (6_000, 34_000)


def test_a_payback_refills_its_purchases_bucket(client, buckets, chequing, savings, add):
    dinner = add(chequing, 12, -8_000, category="dining")
    client.patch(f"/transactions/{dinner.id}", json={"bucket_id": buckets["Fun"]})
    payback = add(savings, 14, 4_000, category="e-transfers")
    client.patch(f"/transactions/{payback.id}", json={"reimburses_id": dinner.id})
    assert state(client)[0]["Fun"] == (4_000, 6_000)

    response = client.patch(f"/transactions/{payback.id}", json={"bucket_id": buckets["Food"]})
    assert response.status_code == 400


def test_split_parts_follow_their_own_categories(client, buckets, chequing, add):
    costco = add(chequing, 12, -10_000, category="groceries")
    client.put(
        f"/transactions/{costco.id}/splits",
        json=[
            {"amount_cents": -7_000, "category": "groceries"},
            {"amount_cents": -3_000, "category": "shopping"},
        ],
    )
    by_name, unbucketed = state(client)
    assert by_name["Food"] == (7_000, 33_000)
    assert unbucketed == 3_000


def test_listing_a_buckets_transactions(client, buckets, chequing, add):
    food = add(chequing, 12, -5_000, category="groceries")
    old = add(chequing, 1, -5_000, category="groceries")  # before the start
    other = add(chequing, 12, -1_000, category="shopping")
    ids = lambda q: [t["id"] for t in client.get(f"/transactions?{q}").json()["items"]]  # noqa: E731
    assert ids(f"bucket_id={buckets['Food']}") == [food.id]
    assert ids("unbucketed=true") == [other.id]
    assert old.id not in ids(f"bucket_id={buckets['Food']}")


def test_category_defaults(client, buckets, chequing, add):
    add(chequing, 12, -5_000, category="groceries")
    add(chequing, 13, -1_000, category="shopping")
    listed = client.get("/budget/categories").json()
    assert listed == [
        {"category": "groceries", "bucket_id": buckets["Food"], "spent_cents": 5_000},
        {"category": "shopping", "bucket_id": None, "spent_cents": 1_000},
        {"category": "dining", "bucket_id": buckets["Food"], "spent_cents": 0},
    ]

    # Changing a default re-sorts past spending too.
    client.put("/budget/categories/shopping", json={"bucket_id": buckets["Fun"]})
    assert state(client)[0]["Fun"] == (1_000, 9_000)
    client.put("/budget/categories/shopping", json={"bucket_id": None})
    assert state(client)[1] == 1_000

    assert (
        client.put("/budget/categories/income", json={"bucket_id": buckets["Fun"]}).status_code
        == 400
    )


def test_archiving_a_bucket_drops_its_category_defaults(client, buckets, chequing, add):
    add(chequing, 12, -5_000, category="groceries")
    client.patch(f"/buckets/{buckets['Food']}", json={"archived": True})
    assert all(c["bucket_id"] is None for c in client.get("/budget/categories").json())
    assert state(client)[1] == 5_000  # unbucketed now
    response = client.put("/budget/categories/groceries", json={"bucket_id": buckets["Food"]})
    assert response.status_code == 400


# --- buckets named like categories ---


def defaults(client):
    return {c["category"]: c["bucket_id"] for c in client.get("/budget/categories").json()}


def new_bucket(client, **body):
    response = client.post("/buckets", json={"type": "recurring", **body})
    assert response.status_code == 201, response.text
    return next(b["id"] for b in response.json()["buckets"] if b["name"] == body["name"])


def test_a_bucket_named_like_a_category_becomes_its_default(client, chequing, add):
    add(chequing, 12, -500, category="transport")
    transport = new_bucket(client, name="Transport")
    assert defaults(client)["transport"] == transport


def test_name_matching_never_replaces_a_chosen_default(client, buckets):
    new_bucket(client, name="Dining")  # dining already defaults to Food
    assert defaults(client)["dining"] == buckets["Food"]


def test_names_that_arent_categories_or_are_income_link_nothing(client, chequing, add):
    add(chequing, 12, 100_000, category="income")
    new_bucket(client, name="Income")
    new_bucket(client, name="Switch 2")
    assert all(b is None for b in defaults(client).values())


def test_renaming_into_a_category_name_links_it(client, chequing, add):
    add(chequing, 12, -500, category="subscriptions")
    bucket = new_bucket(client, name="Streaming")
    client.patch(f"/buckets/{bucket}", json={"name": "Subscriptions"})
    assert defaults(client)["subscriptions"] == bucket


def test_make_a_bucket_for_a_category(client):
    # "taxes" isn't used anywhere yet, so only the explicit category links it.
    taxes = new_bucket(client, name="Tax savings", category="taxes")
    assert defaults(client)["taxes"] == taxes
    response = client.post(
        "/buckets", json={"name": "Pay", "type": "recurring", "category": "income"}
    )
    assert response.status_code == 400


def test_a_taken_name_is_still_a_clear_error(client):
    new_bucket(client, name="Transport")
    response = client.post("/buckets", json={"name": "Transport", "type": "recurring"})
    assert response.status_code == 409
    assert response.json()["detail"] == "there's already a bucket called Transport"
