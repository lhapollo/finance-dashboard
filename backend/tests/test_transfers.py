from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Account, Transaction
from app.services.transfers import detect_transfers


@pytest.fixture
def savings(db_session):
    account = Account(name="Tangerine Savings", institution="Tangerine", type="savings")
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def investing(db_session):
    account = Account(name="Wealthsimple", institution="Wealthsimple", type="investment")
    db_session.add(account)
    db_session.flush()
    return account


@pytest.mark.parametrize(
    "raw",
    [
        "PRE-AUTHORIZED PAYMENT - THANK YOU",
        "PRE AUTHORIZED PAYMENT - THANK YOU",
        "PAYMENT THANK YOU/PAIEMEN T MERCI",
    ],
)
def test_card_payment_is_a_transfer(db_session, card, add, raw):
    payment = add(card, 17, 81240, raw)

    assert detect_transfers(db_session) == 1
    assert payment.is_transfer
    assert payment.transfer_pair_id is None  # bank side not imported yet


def test_purchase_with_payment_in_its_name_is_not_a_transfer(db_session, card, add):
    fee = add(card, 17, -9125, "DRIVE TEST PAYMENT TORONTO, ON")

    detect_transfers(db_session)

    assert not fee.is_transfer


def test_refund_and_cashback_are_not_transfers(db_session, card, add):
    refund = add(card, 12, 2260, "PIZZA PLACE 905-555-0199, ON")
    cashback = add(card, 10, 5000, "CASHBACK/REMISE EN ARGENT")

    assert detect_transfers(db_session) == 0
    assert not refund.is_transfer and not cashback.is_transfer


def test_savings_to_investing_is_paired(db_session, savings, investing, add):
    out = add(savings, 5, -50000)
    arrived = add(investing, 7, 50000)

    assert detect_transfers(db_session) == 2
    assert out.is_transfer and arrived.is_transfer
    assert out.transfer_pair_id == arrived.id
    assert arrived.transfer_pair_id == out.id


def test_bank_side_of_card_payment_pairs_with_card_side(db_session, card, savings, add):
    payment = add(card, 17, 81240, "PRE-AUTHORIZED PAYMENT - THANK YOU")
    withdrawal = add(savings, 16, -81240, "CIBC CARD PAYMENT")

    detect_transfers(db_session)

    assert payment.transfer_pair_id == withdrawal.id
    assert withdrawal.is_transfer


def test_card_credited_before_the_bank_withdraws(db_session, card, savings, add):
    """Real CIBC/Tangerine case: the card shows the payment 4 days before the bank does."""
    payment = add(card, 10, 26125, "PRE-AUTHORIZED PAYMENT - THANK YOU")
    withdrawal = add(savings, 14, -26125, "EFT WITHDRAWAL TO CIBC CPD")

    detect_transfers(db_session)

    assert payment.transfer_pair_id == withdrawal.id


def test_too_far_apart_is_not_paired(db_session, savings, investing, add):
    out = add(savings, 1, -50000)
    arrived = add(investing, 7, 50000)

    assert detect_transfers(db_session) == 0
    assert not out.is_transfer and not arrived.is_transfer


def test_same_account_is_not_paired(db_session, savings, add):
    out = add(savings, 5, -2000)
    back = add(savings, 6, 2000)

    detect_transfers(db_session)

    assert not out.is_transfer and not back.is_transfer


def test_card_purchase_never_pairs(db_session, card, savings, add):
    """A $40 dinner on the card and a friend's $40 e-transfer aren't a transfer."""
    dinner = add(card, 5, -4000, "RESTAURANT")
    repayment = add(savings, 6, 4000, "E-TRANSFER FROM FRIEND")

    detect_transfers(db_session)

    assert not dinner.is_transfer and not repayment.is_transfer


def test_closest_date_wins_and_each_row_pairs_once(db_session, savings, investing, add):
    out = add(savings, 5, -50000)
    far = add(investing, 8, 50000)
    near = add(investing, 6, 50000)

    detect_transfers(db_session)

    assert out.transfer_pair_id == near.id
    assert far.transfer_pair_id is None and not far.is_transfer


def test_manual_choice_is_never_overridden(db_session, card, add):
    payment = add(card, 17, 81240, "PRE-AUTHORIZED PAYMENT - THANK YOU", transfer_source="manual")

    detect_transfers(db_session)

    assert not payment.is_transfer


def test_running_twice_changes_nothing(db_session, card, savings, investing, add):
    add(card, 17, 81240, "PRE-AUTHORIZED PAYMENT - THANK YOU")
    add(savings, 5, -50000)
    add(investing, 6, 50000)

    assert detect_transfers(db_session) == 3
    assert detect_transfers(db_session) == 0


def test_import_marks_card_payments(client, db_session, card):
    sample = (Path(__file__).parent / "fixtures" / "cibc_sample.csv").read_bytes()
    client.post("/import", data={"account_id": card.id}, files={"file": ("c.csv", sample)})

    transfers = db_session.scalars(select(Transaction).where(Transaction.is_transfer)).all()
    assert [t.raw_description for t in transfers] == ["PRE AUTHORIZED PAYMENT - THANK YOU"]
