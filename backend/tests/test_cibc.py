from datetime import date
from pathlib import Path

import pytest

from app.importers.cibc import parse_cibc
from app.importers.common import ImportFormatError, clean_description, dollars_to_cents
from app.services.fingerprint import fingerprints

SAMPLE = Path(__file__).parent / "fixtures" / "cibc_sample.csv"


@pytest.fixture
def sample():
    with SAMPLE.open(newline="") as f:
        return parse_cibc(f)


def test_purchase_becomes_negative_cents(sample):
    t = sample[0]
    assert t.date == date(2026, 10, 18)
    assert t.amount_cents == -4618
    assert t.description == "Loblaws"
    assert t.raw_description == "LOBLAWS #1042 TORONTO, ON"


def test_payment_and_refund_are_positive(sample):
    assert sample[1].amount_cents == 81240  # credit card payment
    assert sample[6].amount_cents == 2260  # refund


def test_blank_lines_are_skipped(sample):
    assert len(sample) == 9


def test_foreign_purchase_uses_cad_amount(sample):
    assert sample[3].amount_cents == -418
    assert sample[3].description == "Fake Transit Paygo"


def test_amount_without_leading_zero(sample):
    assert sample[8].amount_cents == -80


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("LOBLAWS #1042 TORONTO, ON", "Loblaws"),
        ("MCDONALD'S #40359 NORTH YORK, ON", "Mcdonald's"),
        ("SQ *MAPLE LEAF COFFEE NORTH YORK, ON", "Maple Leaf Coffee"),
        ("TST-Paris Baguette Thornhill, ON", "Paris Baguette"),
        ("UNIVERSITY OF WATERLOO - WATERLOO, ON", "University of Waterloo"),
        ("PIZZA PLACE 905-555-0199, ON", "Pizza Place"),
        ("AMZN Mktp CA*530U81W10 866-216-1072, ON", "Amzn Mktp Ca"),
        ("WAL-MART #3001 MISSISSAUGA, ON", "Wal-Mart"),
        ("T&T SUPERMARKET #020 RICHMOND HILL, ON", "T&T Supermarket"),
        ("PRE AUTHORIZED PAYMENT - THANK YOU", "Pre Authorized Payment - Thank You"),
        ("SPOTIFY STOCKHOLM", "Spotify Stockholm"),  # no province: city left alone
    ],
)
def test_clean_description(raw, expected):
    assert clean_description(raw) == expected


@pytest.mark.parametrize(
    "line, message",
    [
        ("10/18/2026,LOBLAWS,46.18,,4500********0000", "not a YYYY-MM-DD date"),
        ("2026-10-18,LOBLAWS,46.18,10.00,4500********0000", "both debit and credit"),
        ("2026-10-18,LOBLAWS,,,4500********0000", "neither debit nor credit"),
        ("2026-10-18,LOBLAWS,46.185,,4500********0000", "not a dollar amount"),
        ("2026-10-18,LOBLAWS,abc,,4500********0000", "not a dollar amount"),
        ("2026-10-18,LOBLAWS,46.18", "expected 5 columns"),
        ("2026-10-18,LOBLAWS,0.00,,4500********0000", "amount is zero"),
    ],
)
def test_bad_rows_fail_loudly_with_line_number(line, message):
    with pytest.raises(ImportFormatError, match=message) as e:
        parse_cibc(["2026-10-19,OK,1.00,,4500********0000", line])
    assert e.value.line == 2


@pytest.mark.parametrize(
    "text, cents", [("46.18", 4618), (".80", 80), ("1,199.94", 119994), ("5", 500), ("0.1", 10)]
)
def test_dollars_to_cents(text, cents):
    assert dollars_to_cents(text) == cents


def test_identical_rows_on_same_day_get_different_fingerprints(sample):
    fps = fingerprints(1, sample)
    assert sample[3] == sample[4]  # two identical subway taps
    assert fps[3] != fps[4]
    assert len(set(fps)) == len(fps)


def test_overlapping_reimport_gives_same_fingerprints(sample):
    """A second download covering Oct 15-18 must match the first one's rows exactly."""
    overlap = [t for t in sample if t.date >= date(2026, 10, 15)]
    full = dict(zip(fingerprints(1, sample), sample, strict=True))
    for fp in fingerprints(1, overlap):
        assert fp in full


def test_fingerprint_depends_on_account(sample):
    assert fingerprints(1, sample) != fingerprints(2, sample)
