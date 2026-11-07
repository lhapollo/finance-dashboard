"""Shared test setup: a separate test database, rebuilt from the migrations once per test run.

Each test runs inside a transaction that's rolled back afterwards, so tests can't see each
other's rows and nothing is left behind.
"""

import itertools
import os
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app
from app.models import Account, Transaction
from app.services import categories

BACKEND = Path(__file__).parent.parent


def _test_database_url() -> str | None:
    """TEST_DATABASE_URL from the environment (CI), or from the repo's .env file (your Mac)."""
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    env_file = BACKEND.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TEST_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


@pytest.fixture(autouse=True)
def no_personal_rules(monkeypatch, tmp_path):
    """Tests only see the committed category rules, never data/category_rules.yaml, so they
    behave the same on your Mac as in CI."""
    monkeypatch.setattr(categories, "PERSONAL_RULES", tmp_path / "no-personal-rules.yaml")


@pytest.fixture(scope="session")
def db_engine():
    url = _test_database_url()
    if url is None:
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_URL isn't set in CI, so database tests would be skipped")
        pytest.skip("set TEST_DATABASE_URL in .env to run database tests (see README)")
    # The migrations below wipe the database, so refuse anything that isn't clearly a test one.
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a database ending in _test")

    engine = create_engine(url)
    cfg = Config(BACKEND / "alembic.ini")
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        # Down then up: checks every migration runs both ways, and starts from a clean slate.
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    with db_engine.connect() as connection:
        outer = connection.begin()
        # The app's session.commit() only commits a savepoint inside our outer transaction.
        session = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield session
        session.close()
        outer.rollback()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def card(db_session):
    """The CIBC account that migration 1 seeds."""
    return db_session.scalar(select(Account).where(Account.name == "CIBC Credit Card"))


@pytest.fixture
def chequing(db_session):
    """The Tangerine Chequing account that migration 6 seeds."""
    return db_session.scalar(select(Account).where(Account.name == "Tangerine Chequing"))


@pytest.fixture
def savings(db_session):
    """The Tangerine Savings account that migration 9 seeds."""
    return db_session.scalar(select(Account).where(Account.name == "Tangerine Savings"))


_ids = itertools.count()


@pytest.fixture
def add(db_session):
    """add(account, day, cents, raw_description, **other_fields): save one row.
    `day` is a day in October 2026, or a full date."""

    def add(account, day, cents, raw="SOMETHING", **fields):
        fields.setdefault("cleaned_description", raw.title())
        fields.setdefault("description", fields["cleaned_description"])
        t = Transaction(
            account=account,
            date=day if isinstance(day, date) else date(2026, 10, day),
            raw_description=raw,
            amount_cents=cents,
            fingerprint=f"test-{next(_ids)}",
            source="csv",
            **fields,
        )
        db_session.add(t)
        db_session.flush()
        return t

    return add
