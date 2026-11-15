from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    institution: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))  # credit / chequing / savings / investment
    # Set when the account's transactions come from Plaid: the bank login, and Plaid's id for
    # this account within it.
    plaid_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("plaid_items.id", ondelete="SET NULL")
    )
    plaid_account_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    # The last day CSV imports cover, set when the account is linked to Plaid. CSV rows after
    # it are skipped on import: Plaid owns those days, and the two would duplicate each other.
    csv_cutoff_date: Mapped[date | None] = mapped_column(Date)
    # Set once I've closed the account (e.g. cancelled a card). Its history stays; it just
    # stops expecting new transactions and isn't counted in available money.
    closed_on: Mapped[date | None] = mapped_column(Date)
    # The balance as the bank last reported it through Plaid, signed like transactions:
    # negative = money I owe (a credit card's balance). None for CSV-only accounts.
    balance_cents: Mapped[int | None] = mapped_column(Integer)
    balance_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    plaid_item: Mapped["PlaidItem | None"] = relationship(back_populates="accounts")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    # The name shown everywhere: the converter's cleaned-up name, unless I renamed it.
    description: Mapped[str] = mapped_column(String(500))
    # The converter's cleaned-up name, never edited. Rename rules match on this, since it's
    # the same every visit ("Presto Fare") while raw_description has a new code each time.
    cleaned_description: Mapped[str] = mapped_column(String(500), index=True)
    # auto = cleaned_description; rule = a rename rule; manual = I renamed just this one.
    description_source: Mapped[str] = mapped_column(
        String(10), default="auto", server_default="auto"
    )
    raw_description: Mapped[str] = mapped_column(String(500))  # exactly what the bank wrote
    # Whole cents: $46.18 is 4618. Negative = money out, positive = money in. Never use float.
    amount_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(50), default="uncategorized", index=True)
    category_source: Mapped[str] = mapped_column(String(10), default="rule")  # rule / manual
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_pair_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    # auto = detection may change is_transfer; manual = I set it by hand, detection leaves it.
    transfer_source: Mapped[str] = mapped_column(String(10), default="auto", server_default="auto")
    # Set on money in that pays back (part of) a purchase, e.g. a friend's e-transfer for their
    # half of dinner. It then counts against the purchase's category, in the purchase's month.
    reimburses_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), index=True
    )
    # Set on money out that someone will pay back in full, e.g. a work dinner. It isn't my
    # spending, so it's left out of every total (and so are paybacks linked to it). Whether
    # it's been paid back yet is worked out from those paybacks: see reimbursement_status.
    reimbursable: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(10))  # csv / plaid
    # Plaid's id for this transaction, so later syncs can update or remove it. Also set on a
    # CSV row that Plaid matched (same account, date and amount), so it isn't added twice.
    plaid_transaction_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    # Not final yet (Plaid only): the amount can still change, e.g. when a tip is added.
    pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    # Which bucket this spending comes out of. Normally that follows the category (see
    # CategoryBucket) and isn't stored; these are only set when I pick one by hand:
    # bucket_assigned_by = "manual", with bucket_id the bucket, or None for "no bucket".
    bucket_id: Mapped[int | None] = mapped_column(ForeignKey("buckets.id", ondelete="SET NULL"))
    bucket_assigned_by: Mapped[str | None] = mapped_column(String(10))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="transactions")
    reimburses: Mapped["Transaction | None"] = relationship(
        foreign_keys=[reimburses_id], remote_side=[id], back_populates="reimbursements"
    )
    reimbursements: Mapped[list["Transaction"]] = relationship(
        foreign_keys=[reimburses_id], back_populates="reimburses", order_by="Transaction.date"
    )
    # The parts this transaction is split into, if any. When there are parts, totals count
    # the parts instead of the whole transaction.
    splits: Mapped[list["TransactionSplit"]] = relationship(
        foreign_keys="TransactionSplit.transaction_id",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionSplit.id",
    )
    # Parts of other transactions that pay this purchase back, e.g. the $45 of a paycheck
    # that covers a work dinner.
    split_paybacks: Mapped[list["TransactionSplit"]] = relationship(
        foreign_keys="TransactionSplit.reimburses_id", back_populates="reimburses"
    )

    @property
    def counted_category(self) -> str:
        """The category this row counts toward: a payback counts as its purchase's category."""
        return self.reimburses.category if self.reimburses is not None else self.category

    @property
    def reimbursement_ids(self) -> list[int]:
        """Transactions that pay this purchase back, whole or through one of their parts."""
        return [r.id for r in self.reimbursements] + [s.transaction_id for s in self.split_paybacks]

    @property
    def reimbursed_cents(self) -> int:
        """How much of this purchase has been paid back (positive)."""
        return sum(r.amount_cents for r in self.reimbursements) + sum(
            s.amount_cents for s in self.split_paybacks
        )

    @property
    def reimbursement_status(self) -> str | None:
        """On a reimbursable purchase: "received" once linked paybacks cover it, else
        "waiting". None on everything else."""
        if not self.reimbursable:
            return None
        return "received" if self.reimbursed_cents >= -self.amount_cents else "waiting"


class TransactionSplit(Base):
    """One part of a split transaction, e.g. the $1,300 of pay and the $45 work
    reimbursement in a $1,345 paycheck. A transaction's parts always add up to its amount.

    A part works like a small transaction: it has its own category, and money in can pay
    back a purchase (reimburses_id), counting against that purchase just as a whole payback
    would. The date, account and transfer flag are the parent transaction's.
    """

    __tablename__ = "transaction_splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)  # same sign as the parent
    category: Mapped[str] = mapped_column(String(50))
    reimburses_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), index=True
    )

    transaction: Mapped[Transaction] = relationship(
        foreign_keys=[transaction_id], back_populates="splits"
    )
    reimburses: Mapped[Transaction | None] = relationship(
        foreign_keys=[reimburses_id], back_populates="split_paybacks"
    )

    @property
    def counted_category(self) -> str:
        """A part that pays back a purchase counts as the purchase's category."""
        return self.reimburses.category if self.reimburses is not None else self.category


class RenameRule(Base):
    """'Show every transaction the converter named <match> as <name>', e.g. Presto Fare -> Presto.

    Rules live in the database (not a YAML file like category rules) because they're
    created from the dashboard.
    """

    __tablename__ = "rename_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    match: Mapped[str] = mapped_column(String(500), unique=True)  # a cleaned_description
    name: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlaidItem(Base):
    """One bank login connected through Plaid. One login can cover several accounts, e.g. a
    Tangerine login covers chequing, savings and the Mastercard."""

    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(100), unique=True)  # Plaid's id for this login
    institution_name: Mapped[str] = mapped_column(String(100))
    # sandbox / production. A sandbox token doesn't work in production, and the other way round.
    environment: Mapped[str] = mapped_column(String(20))
    # Encrypted (see app/services/secrets.py). Never sent to the browser.
    access_token: Mapped[str] = mapped_column(Text)
    # Plaid's bookmark for /transactions/sync: "everything up to here is already saved".
    # Empty until the first sync.
    cursor: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ok, or Plaid's error code from the last sync (e.g. ITEM_LOGIN_REQUIRED).
    status: Mapped[str] = mapped_column(String(50), default="ok", server_default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list[Account]] = relationship(back_populates="plaid_item")


class Bucket(Base):
    """A job for some of my money, e.g. "Rent" or "Switch 2". Buckets are labels, not real
    accounts: the money stays where it is, and the app keeps track of what it's for."""

    __tablename__ = "buckets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # recurring = refilled and spent every paycheck (groceries); goal = saved up for (a Switch 2)
    type: Mapped[str] = mapped_column(String(20))
    target_amount_cents: Mapped[int | None] = mapped_column(Integer)  # required for goals
    target_date: Mapped[date | None] = mapped_column(Date)  # optional, for goals
    # Done with (a goal reached, a bucket I don't need). Hidden, and holds no money.
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    allocations: Mapped[list["Allocation"]] = relationship(
        back_populates="bucket", cascade="all, delete-orphan"
    )


class Allocation(Base):
    """Money put into a bucket (positive) or taken out of it (negative). A bucket's balance is
    the sum of its allocations, minus what's been spent from it.

    Nothing here moves real money; it records a decision I made."""

    __tablename__ = "allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    bucket_id: Mapped[int] = mapped_column(ForeignKey("buckets.id", ondelete="CASCADE"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    # opening_balance = the fresh-start split; assign = to or from unassigned money;
    # move = one side of moving money between buckets; archive = a bucket's leftover going
    # back to unassigned when it's archived; paycheck = a paycheck's split (coming later)
    kind: Mapped[str] = mapped_column(String(20))
    source_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bucket: Mapped[Bucket] = relationship(back_populates="allocations")


class BudgetSettings(Base):
    """One row: when budgeting started. Spending before this date doesn't touch buckets."""

    __tablename__ = "budget_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    start_date: Mapped[date] = mapped_column(Date)


class CategoryBucket(Base):
    """The bucket a category's spending comes out of by default, e.g. groceries -> Food.
    Worked out when totals are calculated, so changing it re-sorts past spending too."""

    __tablename__ = "category_buckets"

    category: Mapped[str] = mapped_column(String(50), primary_key=True)
    bucket_id: Mapped[int] = mapped_column(ForeignKey("buckets.id", ondelete="CASCADE"))
