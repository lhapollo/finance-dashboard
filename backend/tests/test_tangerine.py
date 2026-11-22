from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.importers.common import ImportFormatError
from app.importers.tangerine import (
    clean_tangerine,
    clean_tangerine_card,
    parse_tangerine,
    parse_tangerine_card,
    parse_tangerine_savings,
)
from app.models import Account, Transaction

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "tangerine_sample.csv"
HEADER = "Date,Transaction,Name,Memo,Amount"


@pytest.fixture
def sample():
    with SAMPLE.open(newline="") as f:
        return parse_tangerine(f)


def test_rows_become_standard_transactions(sample):
    paycheck = sample[0]
    assert paycheck.date == date(2026, 10, 1)
    assert paycheck.amount_cents == 250000
    assert paycheck.description == "Rippling Canada"


def test_amounts_keep_their_sign(sample):
    assert sample[1].amount_cents == -100000
    assert sample[-1].amount_cents == 1  # one cent of interest


def test_zero_amount_notes_and_blank_lines_are_skipped(sample):
    assert len(sample) == 9
    assert not any("Posted" in t.raw_description for t in sample)


def test_raw_description_is_kept_exactly(sample):
    assert sample[2].raw_description == "Interac - Purchase - LOBLAWS #1042 TORONTO  ON  CA"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Interac - Purchase - LOBLAWS #1042 TORONTO  ON  CA", "Loblaws"),
        ("Interac - Purchase - RAMONA'S KITCHEN RICHMOND H  ON  CA", "Ramona's Kitchen"),
        ("Interac - Purchase - BOOSTER JUICE # TORONTO  ON  CA", "Booster Juice"),
        ("Visa Debit - Purchase - STUBHUB CANADA LTD TORONTO  CA", "Stubhub Canada Ltd"),
        # Plaid's wording of the same purchases: commas instead of double spaces.
        ("Interac - Purchase - BOOSTER JUICE # TORONTO, ON, CA", "Booster Juice"),
        ("Visa Debit - Purchase - Amazon.ca*A040Z7H73 866-216-1072, CA", "Amazon.ca"),
        ("INTERAC e-Transfer To: sam example", "e-Transfer to Sam Example"),
        ("INTERAC e-Transfer From: SAM EXAMPLE", "e-Transfer from Sam Example"),
        ("Cancelled INTERAC e-Transfer To: Sam Example", "Cancelled e-Transfer to Sam Example"),
        (
            "Internet Deposit from Tangerine Savings Account - 1234567890",
            "Transfer from Tangerine Savings",
        ),
        (
            "Recurring Internet Withdrawal to Tangerine Savings Account - 1234567890",
            "Recurring transfer to Tangerine Savings",
        ),
        ("EFT Deposit from Rippling Canada", "Rippling Canada"),
        ("EFT Deposit CAD ESSENTIALS from CANADA", "Canada"),
        ("EFT Withdrawal to WS Investments", "Payment to Ws Investments"),
        ("Bill Payment - CIBC VISA - ************0000", "Bill Payment - Cibc Visa"),
        ("Interest Paid", "Interest Paid"),
    ],
)
def test_clean_tangerine(raw, expected):
    assert clean_tangerine(raw) == expected


@pytest.mark.parametrize(
    "lines, line, message",
    [
        (["Date,Amount", "10/01/2026,1.00"], 1, "expected the header"),
        ([HEADER, "2026-10-01,OTHER,X,X,1.00"], 2, "not a MM/DD/YYYY date"),
        ([HEADER, "13/01/2026,OTHER,X,X,1.00"], 2, "not a MM/DD/YYYY date"),  # day first
        ([HEADER, "10/01/2026,OTHER,X,X,1.005"], 2, "not a dollar amount"),
        ([HEADER, "10/01/2026,OTHER,X,1.00"], 2, "expected 5 columns"),
    ],
)
def test_bad_files_fail_loudly(lines, line, message):
    with pytest.raises(ImportFormatError, match=message) as e:
        parse_tangerine(lines)
    assert e.value.line == line


def upload(client, account, path):
    return client.post(
        "/import", data={"account_id": account.id}, files={"file": (path.name, path.read_bytes())}
    )


def test_import_marks_own_transfers_and_categorizes(client, db_session, chequing):
    response = upload(client, chequing, SAMPLE)

    assert response.json() == {"inserted": 9, "skipped": 0, "from_plaid": 0}
    by_raw = {t.raw_description: t for t in db_session.scalars(select(Transaction))}
    to_savings = by_raw["Internet Withdrawal to Tangerine Savings Account - 1234567890"]
    assert to_savings.is_transfer and to_savings.transfer_pair_id is None  # savings not imported
    assert by_raw["EFT Deposit from Rippling Canada"].category == "income"
    assert by_raw["INTERAC e-Transfer To: Sam Example"].category == "e-transfers"
    assert by_raw["Visa Debit - Purchase - STUBHUB CANADA LTD TORONTO  CA"].category == (
        "entertainment"
    )


def test_identical_purchases_on_one_day_are_both_kept(client, db_session, chequing):
    upload(client, chequing, SAMPLE)

    loblaws = db_session.scalars(
        select(Transaction).where(Transaction.cleaned_description == "Loblaws")
    ).all()
    assert len(loblaws) == 2


def test_card_payment_pairs_with_the_card_side(client, db_session, card, chequing):
    """Paying the CIBC card from chequing: -812.40 here, +812.40 on the card two days later."""
    upload(client, card, FIXTURES / "cibc_sample.csv")
    upload(client, chequing, SAMPLE)

    bank_side = db_session.scalar(
        select(Transaction).where(Transaction.raw_description == "EFT Withdrawal to CIBC CPD")
    )
    card_side = db_session.get(Transaction, bank_side.transfer_pair_id)
    assert card_side.raw_description == "PRE AUTHORIZED PAYMENT - THANK YOU"
    assert card_side.transfer_pair_id == bank_side.id
    assert bank_side.is_transfer and card_side.is_transfer


def test_reimporting_skips_everything(client, chequing):
    upload(client, chequing, SAMPLE)

    assert upload(client, chequing, SAMPLE).json() == {
        "inserted": 0,
        "skipped": 9,
        "from_plaid": 0,
    }


# --- Mastercard ----------------------------------------------------------------------------

CARD_SAMPLE = FIXTURES / "tangerine_card_sample.csv"


@pytest.fixture
def card_sample():
    with CARD_SAMPLE.open(newline="") as f:
        return parse_tangerine_card(f)


@pytest.fixture
def mastercard(db_session):
    """The account that migration 7 seeds."""
    return db_session.scalar(select(Account).where(Account.name == "Tangerine Mastercard"))


def test_card_rows(card_sample):
    assert len(card_sample) == 6
    uber = card_sample[0]
    assert (uber.date, uber.amount_cents) == (date(2026, 10, 31), -8095)
    assert uber.raw_description == "UBER CANADA/UBERTRIP TORONTO ON"  # Name, not the rewards memo
    assert card_sample[2].amount_cents == 53711  # the payment is money in


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ZEN KYOTO TORONTO ON", "Zen Kyoto"),
        ("SANSOTEI RAMEN ADELAID TORONTO O", "Sansotei Ramen Adelaid"),  # province cut to "O"
        ("SQ *THE POKE BOX TORON Toronto O", "The Poke Box Toron"),
        ("Heytea Markham ON", "Heytea"),
        ("DOLLARAMA # 652 TORONTO ON", "Dollarama"),
        ("CHIPOTLE ONLINE HALIFAX NS", "Chipotle Online"),
        ("PAYMENT - THANK YOU", "Payment - Thank You"),
    ],
)
def test_clean_tangerine_card(raw, expected):
    assert clean_tangerine_card(raw) == expected


def test_card_and_chequing_files_are_told_apart():
    """Each parser checks its header, so uploading to the wrong account fails loudly."""
    with pytest.raises(ImportFormatError, match="Transaction date"):
        parse_tangerine_card(SAMPLE.read_text().splitlines())
    with pytest.raises(ImportFormatError, match="expected the header Date,"):
        parse_tangerine(CARD_SAMPLE.read_text().splitlines())


def test_card_payment_pairs_with_chequing(client, db_session, chequing, mastercard, add):
    withdrawal = add(chequing, 28, -53711, "Tangerine Credit Card Payment")

    response = upload(client, mastercard, CARD_SAMPLE)

    assert response.json() == {"inserted": 6, "skipped": 0, "from_plaid": 0}
    payment = db_session.scalar(
        select(Transaction).where(Transaction.raw_description == "PAYMENT - THANK YOU")
    )
    assert payment.is_transfer and payment.transfer_pair_id == withdrawal.id
    assert withdrawal.transfer_pair_id == payment.id
    heytea = db_session.scalars(
        select(Transaction).where(Transaction.cleaned_description == "Heytea")
    ).all()
    assert len(heytea) == 2 and heytea[0].category == "dining"


# --- Savings -------------------------------------------------------------------------------

SAVINGS_SAMPLE = FIXTURES / "tangerine_savings_sample.csv"


def test_savings_rows():
    with SAVINGS_SAMPLE.open(newline="") as f:
        rows = parse_tangerine_savings(f)

    assert len(rows) == 7  # the 0.00 interest note is skipped
    assert (rows[1].date, rows[1].amount_cents) == (date(2026, 10, 2), 100000)
    assert rows[1].description == "Transfer from Tangerine Chequing"
    assert rows[3].amount_cents == -25000


def test_chequing_and_savings_files_are_told_apart():
    """Same header, but a file never transfers to its own account, so a mix-up fails loudly."""
    with pytest.raises(ImportFormatError, match="looks like a chequing export") as e:
        parse_tangerine_savings(SAMPLE.read_text().splitlines())
    assert e.value.line == 3  # the withdrawal to Tangerine Savings
    with pytest.raises(ImportFormatError, match="looks like a savings export") as e:
        parse_tangerine(SAVINGS_SAMPLE.read_text().splitlines())
    assert e.value.line == 3  # the deposit from Tangerine Chequing


def test_savings_pairs_with_chequing_and_categorizes(client, db_session, chequing, savings):
    """Chequing sends 1000.00 to savings on Oct 2: both sides are one transfer, not income."""
    upload(client, chequing, SAMPLE)
    response = upload(client, savings, SAVINGS_SAMPLE)

    assert response.json() == {"inserted": 7, "skipped": 0, "from_plaid": 0}
    by_raw = {t.raw_description: t for t in db_session.scalars(select(Transaction))}
    deposit = by_raw["Internet Deposit from Tangerine Chequing Account - 1234567891"]
    withdrawal = by_raw["Internet Withdrawal to Tangerine Savings Account - 1234567890"]
    assert deposit.transfer_pair_id == withdrawal.id
    assert withdrawal.transfer_pair_id == deposit.id
    assert by_raw["Internet Withdrawal to Tangerine Chequing Account - 1234567891"].is_transfer
    assert by_raw["Promotional Bonus Interest"].category == "income"
    assert by_raw["Interest Paid"].category == "income"
    assert by_raw["Credit Card Rewards Redemption"].category == "rewards"
    assert not by_raw["INTERAC e-Transfer From: SAM EXAMPLE"].is_transfer
