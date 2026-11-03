from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func
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
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(10))  # csv / plaid
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="transactions")


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
