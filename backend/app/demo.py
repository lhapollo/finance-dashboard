"""Fake data: a believable year of someone's money, for the demo and for safe testing.

    python -m app.demo            # create the demo database if needed, seed it if empty
    python -m app.demo --reset    # wipe it and seed it again

It only ever touches a database whose name ends in "_demo" (DATABASE_URL, which docker-compose
points at finance_demo for the demo services), so it can never overwrite real data.

Everything is made up: the employer, landlord, friends and amounts. Dates are relative to
today, so the demo always looks current. The same seed gives the same data every time.
"""

import argparse
import random
from datetime import UTC, date, datetime, timedelta

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import config
from app.importers.common import clean_description
from app.importers.plaid import CLEANERS
from app.models import (
    Account,
    Allocation,
    Bucket,
    BudgetSettings,
    CategoryBucket,
    IncomeSource,
    PaycheckRule,
    Transaction,
)
from app.services.budget import budget
from app.services.clock import today
from app.services.paychecks import paycheck_cents, suggest_split
from app.services.transfers import detect_transfers

EMPLOYER = "EFT Deposit from Maple Leaf Software Inc"
PAY_CENTS = 245_000  # every two weeks

# (raw description, category, low $, high $)
GROCERIES = [
    ("LOBLAWS #1042 TORONTO ON", 35, 120),
    ("NO FRILLS #3381 TORONTO ON", 25, 90),
    ("METRO 512 TORONTO ON", 20, 80),
    ("FARM BOY #27 TORONTO ON", 30, 95),
]
DINING = [
    ("TIM HORTONS #2231 TORONTO ON", 2, 9),
    ("PAI NORTHERN THAI TORONTO ON", 22, 48),
    ("SANSOTEI RAMEN TORONTO ON", 17, 32),
    ("BURRITO BOYZ TORONTO ON", 13, 22),
    ("UBER EATS TORONTO ON", 18, 45),
    ("BALZAC'S COFFEE TORONTO ON", 4, 9),
]
SHOPPING = [
    ("AMZN Mktp CA*AB12CD34E WWW.AMAZON.CA ON", 15, 90),
    ("UNIQLO EATON CENTRE TORONTO ON", 25, 80),
    ("INDIGO #812 TORONTO ON", 12, 45),
]

# Emptied before seeding. Accounts stay (migrations create them), so plaid_items isn't here:
# TRUNCATE ... CASCADE would empty accounts too, since accounts point at plaid_items.
_TABLES = [
    "allocations",
    "paycheck_rules",
    "category_buckets",
    "income_sources",
    "budget_settings",
    "transaction_splits",
    "transactions",
    "buckets",
    "rename_rules",
]


def seed(session: Session, day: date, rng: random.Random) -> None:
    """Fill an empty database (accounts only) with a year of activity and a budget."""
    accounts = {a.name: a for a in session.scalars(select(Account))}
    chequing = accounts["Tangerine Chequing"]
    savings = accounts["Tangerine Savings"]
    mastercard = accounts["Tangerine Mastercard"]
    cibc = accounts["CIBC Credit Card"]

    rows: list[Transaction] = []
    first = day - timedelta(days=364)
    switched = day - timedelta(days=180)  # moved from the CIBC card to the Mastercard
    card_owed = {cibc.id: 0, mastercard.id: 0}

    def add(account, d, cents, raw, category, **fields):
        # Named the way the real converters would name it ("Pai Northern Thai").
        name = CLEANERS.get((account.institution, account.type), clean_description)(raw)
        t = Transaction(
            account=account,
            date=d,
            description=name,
            cleaned_description=name,
            raw_description=raw,
            amount_cents=cents,
            category=category,
            category_source="rule",
            fingerprint=f"demo-{len(rows)}",
            source="csv",
            **fields,
        )
        rows.append(t)
        if account.type == "credit":
            card_owed[account.id] -= cents
        return t

    def dollars(low, high):
        return rng.randint(low * 100, high * 100)

    pay_anchor = first + timedelta(days=(4 - first.weekday()) % 7)  # a Friday
    d = first
    while d <= day:
        card = cibc if d < switched else mastercard
        if (d - pay_anchor).days % 14 == 0 and d >= pay_anchor:
            add(chequing, d, PAY_CENTS, EMPLOYER, "income")
        if d.day == 1:
            add(chequing, d, -135_000, "INTERAC e-Transfer To: Riverside Properties", "home")
        if d.day == 2:
            add(
                chequing,
                d,
                -50_000,
                "Internet Withdrawal to Tangerine Savings Account - 4402918833",
                "uncategorized",
            )
            add(
                savings,
                d,
                50_000,
                "Internet Deposit from Tangerine Chequing Account - 4402911177",
                "uncategorized",
            )
        if (d + timedelta(days=1)).day == 1:
            add(savings, d, rng.randint(180, 420), "Interest Paid", "income")
        if d.day == 20:
            for c in (cibc, mastercard):
                owed = card_owed[c.id]
                if owed > 0:
                    if c is cibc:
                        add(
                            chequing,
                            d,
                            -owed,
                            "Bill Payment - CIBC VISA - ************1234",
                            "uncategorized",
                        )
                        add(c, d, owed, "PAYMENT THANK YOU/PAIEMENT MERCI", "uncategorized")
                    else:
                        add(chequing, d, -owed, "Tangerine Credit Card Payment", "uncategorized")
                        add(c, d, owed, "PAYMENT - THANK YOU", "uncategorized")
        if d.day == 5:
            add(card, d, -1_199, "SPOTIFY P1A2B3C4D5 STOCKHOLM", "subscriptions")
        if d.day == 12:
            add(card, d, -1_649, "NETFLIX.COM 866-579-7172 ON", "subscriptions")
        if d.weekday() in (2, 5):  # Wednesday and Saturday
            raw, low, high = rng.choice(GROCERIES)
            add(card, d, -dollars(low, high), raw, "groceries")
        for _ in range(2 if rng.random() < 0.15 else 1 if rng.random() < 0.4 else 0):
            raw, low, high = rng.choice(DINING)
            add(card, d, -dollars(low, high), raw, "dining")
        if d.weekday() < 5 and rng.random() < 0.6:
            add(card, d, -330, "PRESTO FARE/TORONTO", "transport")
        if rng.random() < 0.06:
            raw, low, high = rng.choice(SHOPPING)
            add(card, d, -dollars(low, high), raw, "shopping")
        if rng.random() < 0.03:
            add(card, d, -dollars(10, 80), "NINTENDO CA1234567 800-255-3700 WA", "games")
        if rng.random() < 0.04:
            add(card, d, -dollars(14, 30), "CINEPLEX #9 TORONTO ON", "entertainment")
        d += timedelta(days=1)

    # A few stories the app handles specially.
    shared = add(
        mastercard, day - timedelta(days=24), -12_000, "THE KEG STEAKHOUSE TORONTO ON", "dining"
    )
    add(
        chequing,
        day - timedelta(days=22),
        6_000,
        "INTERAC e-Transfer From: Jordan Lee",
        "e-transfers",
        reimburses=shared,
    )
    work = add(
        mastercard,
        day - timedelta(days=18),
        -8_640,
        "MILESTONES GRILL TORONTO ON",
        "dining",
        reimbursable=True,
    )
    add(
        chequing,
        day - timedelta(days=9),
        8_640,
        "EFT Deposit from Expensify Inc",
        "e-transfers",
        reimburses=work,
    )
    returned = add(
        mastercard,
        day - timedelta(days=40),
        -6_499,
        "AMZN Mktp CA*RT56YU78Z WWW.AMAZON.CA ON",
        "shopping",
    )
    add(
        mastercard,
        day - timedelta(days=33),
        -returned.amount_cents,
        "AMZN Mktp CA*RT56YU78Z WWW.AMAZON.CA ON",
        "shopping",
    )
    add(mastercard, day, -2_315, "PAI NORTHERN THAI TORONTO ON", "dining", pending=True)

    session.add_all(rows)
    session.flush()
    detect_transfers(session)

    # Balances, as Plaid would report them: what each account started with, plus everything
    # that's posted (banks leave pending transactions out).
    starting = {chequing.id: 180_000, savings.id: 400_000}
    now = datetime.now(UTC)
    for account in (chequing, savings, mastercard, cibc):
        moved = sum(t.amount_cents for t in rows if t.account_id == account.id and not t.pending)
        account.balance_cents = starting.get(account.id, 0) + moved
        account.balance_updated_at = now
    cibc.closed_on = switched + timedelta(days=35)  # after its last payment

    _seed_budget(session, day, chequing, rows)


def _seed_budget(session: Session, day: date, chequing: Account, rows: list[Transaction]) -> None:
    """A budget that started 30 days ago, with its paychecks split except the newest."""
    start = day - timedelta(days=30)
    session.add(BudgetSettings(id=1, start_date=start))

    def bucket(name, opening, type="recurring", **fields):
        b = Bucket(name=name, type=type, **fields)
        session.add(b)
        session.flush()
        if opening:
            session.add(
                Allocation(bucket=b, amount_cents=opening, date=start, kind="opening_balance")
            )
        return b

    rent = bucket("Rent", 135_000)
    groceries = bucket("Groceries", 30_000)
    dining = bucket("Dining", 20_000)
    transport = bucket("Transport", 8_000)
    subscriptions = bucket("Subscriptions", 3_000)
    fun = bucket("Fun", 15_000)
    switch = bucket(
        "Switch 2", 12_000, "goal", target_amount_cents=50_000, target_date=day + timedelta(days=40)
    )
    emergency = bucket("Emergency fund", 150_000, "goal", target_amount_cents=500_000)

    for category, b in [
        ("home", rent),
        ("groceries", groceries),
        ("dining", dining),
        ("transport", transport),
        ("subscriptions", subscriptions),
        ("shopping", fun),
        ("games", fun),
        ("entertainment", fun),
    ]:
        session.add(CategoryBucket(category=category, bucket_id=b.id))

    session.add(IncomeSource(name="Maple Leaf Software", account=chequing, match_text="Maple Leaf"))
    rules = [
        PaycheckRule(bucket_id=rent.id, kind="fixed", amount_cents=67_500, priority=0),
        PaycheckRule(bucket_id=groceries.id, kind="fixed", amount_cents=15_000, priority=1),
        PaycheckRule(bucket_id=dining.id, kind="fixed", amount_cents=10_000, priority=2),
        PaycheckRule(bucket_id=transport.id, kind="fixed", amount_cents=4_000, priority=3),
        PaycheckRule(bucket_id=subscriptions.id, kind="fixed", amount_cents=1_500, priority=4),
        PaycheckRule(bucket_id=fun.id, kind="percent", percent=10, priority=5),
        PaycheckRule(bucket_id=switch.id, kind="percent", percent=15, priority=6),
        PaycheckRule(bucket_id=emergency.id, kind="percent", percent=25, priority=7),
    ]
    session.add_all(rules)
    session.flush()

    paychecks = sorted(
        (t for t in rows if t.raw_description == EMPLOYER and t.date >= start), key=lambda t: t.date
    )
    newest = paychecks[-1]
    for t in paychecks[:-1]:  # the newest is left for the "split it" reminder
        for part in suggest_split(paycheck_cents(t), rules).suggested:
            session.add(
                Allocation(
                    bucket_id=part.bucket_id,
                    amount_cents=part.amount_cents,
                    date=t.date,
                    kind="paycheck",
                    source_transaction_id=t.id,
                    note=f"Paycheck {t.date.isoformat()}",
                )
            )
    session.flush()

    # A year of pay adds up: park what isn't otherwise budgeted in the emergency fund, so
    # unassigned is just the newest paycheck plus a little, like a real budget would be.
    extra = (budget(session).unassigned_cents or 0) - paycheck_cents(newest) - 25_000
    if extra > 0:
        opening = session.scalar(
            select(Allocation).where(
                Allocation.bucket_id == emergency.id, Allocation.kind == "opening_balance"
            )
        )
        opening.amount_cents += extra
        emergency.target_amount_cents = max(
            500_000, (opening.amount_cents * 3 // 2) // 100_000 * 100_000
        )
        session.flush()


def _wipe(session: Session) -> None:
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.execute(
        text(
            "UPDATE accounts SET plaid_item_id = NULL, plaid_account_id = NULL, "
            "csv_cutoff_date = NULL, closed_on = NULL, balance_cents = NULL, "
            "balance_updated_at = NULL"
        )
    )
    session.execute(text("DELETE FROM plaid_items"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="wipe the demo data and seed again")
    args = parser.parse_args()

    url = make_url(config.DATABASE_URL)
    if not (url.database or "").endswith("_demo"):
        raise SystemExit(f"refusing to touch {url.database!r}: the demo database must end in _demo")

    # Create the database the first time. CREATE DATABASE can't run inside a transaction.
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
            print(f"created {url.database}")
    admin.dispose()

    engine = create_engine(url)
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")

    with Session(engine) as session:
        empty = session.scalar(select(func.count()).select_from(Transaction)) == 0
        if args.reset or empty:
            _wipe(session)
            seed(session, today(), random.Random(2026))
            session.commit()
            count = session.scalar(select(func.count()).select_from(Transaction))
            print(f"seeded {url.database} with {count} fake transactions")
        else:
            print(f"{url.database} already has data; use --reset to start over")


if __name__ == "__main__":
    main()
