"""Reimbursable purchases: money out that someone will pay all of back, e.g. a work dinner.
They aren't my spending, and the paybacks for them aren't my income."""

from datetime import date

import pytest

from app.services.transfers import detect_transfers


@pytest.fixture
def work_dinner(card, add):
    """$45 team dinner on October 10 that work pays back."""
    return add(card, 10, -4500, "PIZZA PLACE", category="dining")


@pytest.fixture
def groceries(card, add):
    return add(card, 12, -6000, "LOBLAWS", category="groceries")


def patch(client, t, **body):
    return client.patch(f"/transactions/{t.id}", json=body)


def month(client, m="2026-10"):
    return client.get("/summary/month", params={"month": m}).json()


def categories(client):
    body = client.get(
        "/summary/categories", params={"start": "2026-10-01", "end": "2026-11-01"}
    ).json()
    return {c["category"]: c["total_cents"] for c in body}


def waiting(client):
    return client.get("/summary/reimbursements").json()


def test_reimbursable_purchase_is_not_spending(client, work_dinner, groceries):
    response = patch(client, work_dinner, reimbursable=True)

    assert response.json()["reimbursable"] is True
    assert response.json()["reimbursement_status"] == "waiting"
    assert month(client)["spent_cents"] == 6000
    assert categories(client) == {"groceries": 6000}
    over_time = client.get("/summary/over-time", params={"month": "2026-10", "months": 1})
    assert over_time.json() == [
        {"period": "2026-10-01", "category": "groceries", "total_cents": 6000}
    ]


def test_waiting_to_be_reimbursed(client, work_dinner, groceries):
    assert waiting(client) == {"waiting_cents": 0, "count": 0}

    patch(client, work_dinner, reimbursable=True)

    assert waiting(client) == {"waiting_cents": 4500, "count": 1}


def test_payback_for_it_is_not_income(client, chequing, add, work_dinner):
    """Work pays the $45 back in November: not income, and nothing is owed any more."""
    payback = add(chequing, date(2026, 11, 14), 4500, "EFT DEPOSIT FROM EMPLOYER")
    patch(client, work_dinner, reimbursable=True)

    linked = patch(client, payback, reimburses_id=work_dinner.id)

    assert linked.status_code == 200
    november = month(client, "2026-11")
    assert (november["spent_cents"], november["income_cents"]) == (0, 0)
    assert waiting(client) == {"waiting_cents": 0, "count": 0}
    dinner = client.get(f"/transactions/{work_dinner.id}").json()
    assert dinner["reimbursement_status"] == "received"


def test_partly_paid_back_is_still_waiting(client, chequing, add, work_dinner):
    payback = add(chequing, 20, 2000, "EFT DEPOSIT FROM EMPLOYER")
    patch(client, work_dinner, reimbursable=True)
    patch(client, payback, reimburses_id=work_dinner.id)

    assert waiting(client) == {"waiting_cents": 2500, "count": 1}
    assert month(client)["spent_cents"] == 0  # neither side counts


def test_unmarking_counts_it_again(client, work_dinner):
    patch(client, work_dinner, reimbursable=True)

    response = patch(client, work_dinner, reimbursable=False)

    assert response.json()["reimbursement_status"] is None
    assert month(client)["spent_cents"] == 4500


def test_list_filter(client, work_dinner, groceries):
    patch(client, work_dinner, reimbursable=True)

    body = client.get("/transactions", params={"reimbursable": True}).json()

    assert [t["id"] for t in body["items"]] == [work_dinner.id]


@pytest.mark.parametrize(
    "cents, transfer, message",
    [
        (4500, False, "only money out can be reimbursable"),
        (-4500, True, "a transfer can't be reimbursable"),
    ],
)
def test_what_cant_be_reimbursable(client, card, add, cents, transfer, message):
    t = add(card, 5, cents, "SOMETHING", is_transfer=transfer)

    response = patch(client, t, reimbursable=True)

    assert response.status_code == 400
    assert response.json()["detail"] == message


def test_reimbursable_purchase_cant_become_a_transfer(client, work_dinner):
    patch(client, work_dinner, reimbursable=True)

    response = patch(client, work_dinner, is_transfer=True)

    assert response.status_code == 400


def test_transfer_detection_leaves_it_alone(db_session, client, chequing, savings, add):
    """A $500 reimbursable expense and $500 arriving in savings the next day stay as they are."""
    expense = add(chequing, 5, -50000, "CONFERENCE TICKET")
    arrived = add(savings, 6, 50000)
    patch(client, expense, reimbursable=True)

    detect_transfers(db_session)

    assert not expense.is_transfer and not arrived.is_transfer
