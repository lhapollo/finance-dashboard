from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    institution: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))  # credit / chequing / savings / investment

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


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
