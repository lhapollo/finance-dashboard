from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Account, Transaction

SAMPLE = (Path(__file__).parent / "fixtures" / "cibc_sample.csv").read_bytes()


@pytest.fixture
def cibc(db_session):
    """The CIBC account that migration 1 seeds."""
    return db_session.scalar(select(Account).where(Account.name == "CIBC Credit Card"))


def upload(client, account_id, content, filename="cibc.csv"):
    return client.post(
        "/import", data={"account_id": account_id}, files={"file": (filename, content)}
    )


def count(db_session):
    return db_session.scalar(select(func.count()).select_from(Transaction))


def test_import_saves_every_row(client, db_session, cibc):
    response = upload(client, cibc.id, SAMPLE)

    assert response.status_code == 200
    assert response.json() == {"inserted": 9, "skipped": 0}
    loblaws = db_session.scalar(select(Transaction).where(Transaction.description == "Loblaws"))
    assert loblaws.amount_cents == -4618
    assert loblaws.raw_description == "LOBLAWS #1042 TORONTO, ON"
    assert loblaws.account_id == cibc.id
    assert loblaws.category == "groceries"
    assert loblaws.source == "csv"


def test_importing_the_same_file_twice_skips_everything(client, db_session, cibc):
    upload(client, cibc.id, SAMPLE)
    response = upload(client, cibc.id, SAMPLE)

    assert response.json() == {"inserted": 0, "skipped": 9}
    assert count(db_session) == 9


def test_overlapping_download_only_adds_new_rows(client, db_session, cibc):
    lines = SAMPLE.splitlines(keepends=True)
    older_half = b"".join(lines[5:])  # Oct 9-14 (plus the blank line)
    upload(client, cibc.id, older_half)

    response = upload(client, cibc.id, SAMPLE)

    assert response.json() == {"inserted": 5, "skipped": 4}
    assert count(db_session) == 9


def test_excel_byte_order_mark_is_ignored(client, cibc):
    response = upload(client, cibc.id, b"\xef\xbb\xbf" + SAMPLE)

    assert response.json()["inserted"] == 9


def test_bad_row_saves_nothing(client, db_session, cibc):
    bad = SAMPLE + b"not-a-date,OOPS,1.00,,4500********0000\n"

    response = upload(client, cibc.id, bad)

    assert response.status_code == 400
    assert "line 11" in response.json()["detail"]
    assert count(db_session) == 0


def test_unknown_account(client):
    assert upload(client, 999_999, SAMPLE).status_code == 404


def test_account_without_converter(client, db_session):
    account = Account(name="Tangerine Savings", institution="Tangerine", type="savings")
    db_session.add(account)
    db_session.flush()

    response = upload(client, account.id, SAMPLE)

    assert response.status_code == 400
    assert "no CSV converter" in response.json()["detail"]


def test_non_text_file(client, cibc):
    response = upload(client, cibc.id, b"\x89PNG\r\n\x1a\n\xff\xfe", filename="photo.png")

    assert response.status_code == 400


def test_empty_file(client, cibc):
    response = upload(client, cibc.id, b"\n\n")

    assert response.status_code == 400
    assert response.json()["detail"] == "file has no transactions"
