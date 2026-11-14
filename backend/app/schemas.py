from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StandardTransaction(BaseModel):
    """The one format every importer must output. The rest of the app only sees this."""

    model_config = ConfigDict(frozen=True)

    date: date
    description: str = Field(min_length=1, max_length=500)  # cleaned-up merchant name
    # Exactly what the bank wrote, kept so a bad cleanup never loses information.
    raw_description: str = Field(min_length=1, max_length=500)
    # Whole cents; negative = money out. strict: a float like 46.18 is rejected, not coerced.
    amount_cents: int = Field(strict=True)
    source: Literal["csv", "plaid"] = "csv"

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("description is blank")
        return v

    @field_validator("amount_cents")
    @classmethod
    def nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("amount is zero")
        return v


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    institution: str
    type: str


def _tidy_category(v: str) -> str:
    # "Dining " and "dining" should be one category, not two.
    v = " ".join(v.split()).lower()
    if not v:
        raise ValueError("category is blank")
    return v


class SplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount_cents: int  # same sign as the transaction
    category: str
    reimburses_id: int | None  # on money in: the purchase this part pays back
    counted_category: str  # the purchase's category if it pays one back, else `category`


class SplitIn(BaseModel):
    amount_cents: int = Field(strict=True)
    category: str = Field(min_length=1, max_length=50)
    reimburses_id: int | None = None

    @field_validator("category")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        return _tidy_category(v)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    date: date
    description: str  # the name to show
    cleaned_description: str  # the converter's name, before any rename
    description_source: str  # auto / rule / manual
    raw_description: str
    amount_cents: int
    category: str
    category_source: str
    is_transfer: bool
    transfer_source: str
    transfer_pair_id: int | None
    # Paybacks: money in that pays back a purchase counts in the purchase's category.
    reimburses_id: int | None  # on a payback: the purchase it pays back
    counted_category: str  # the purchase's category on a payback, otherwise `category`
    reimbursement_ids: list[int]  # on a purchase: the paybacks linked to it, oldest first
    reimbursed_cents: int  # on a purchase: how much has been paid back (positive)
    # Someone will pay all of it back, so it isn't counted as my spending.
    reimbursable: bool
    reimbursement_status: Literal["waiting", "received"] | None  # None unless reimbursable
    # The parts this transaction is split into; empty if it isn't split. When there are
    # parts, they count instead of the whole transaction.
    splits: list[SplitOut]
    imported_at: datetime


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int


class TransactionUpdate(BaseModel):
    """Only the fields you send are changed. Each change locks that field against the rules.

    description: a new name for this transaction. Send null to undo a rename. With
    rename_all, every transaction from the same merchant gets the name, now and in future
    imports, instead of just this one.

    reimburses_id: on money in, the purchase it pays back. Send null to unlink.

    reimbursable: on money out, true if someone will pay all of it back (a work expense),
    so it isn't counted as spending. Link the payback with reimburses_id when it arrives.
    """

    category: str | None = Field(default=None, min_length=1, max_length=50)
    is_transfer: bool | None = None
    description: str | None = Field(default=None, max_length=500)
    rename_all: bool = False
    reimburses_id: int | None = None
    reimbursable: bool | None = None

    @field_validator("description")
    @classmethod
    def tidy_description(cls, v: str | None) -> str | None:
        if v is not None:
            v = " ".join(v.split())
            if not v:
                raise ValueError("name is blank")
        return v

    @field_validator("category")
    @classmethod
    def normalize_category(cls, v: str | None) -> str | None:
        return None if v is None else _tidy_category(v)


class RecategorizeResult(BaseModel):
    changed: int


class RenameRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match: str
    name: str


class CategoryTotal(BaseModel):
    category: str
    total_cents: int  # positive number = amount spent


class PeriodCategoryTotal(BaseModel):
    period: date  # first day of the month (or year)
    category: str
    total_cents: int  # positive number = amount spent


class MonthSummary(BaseModel):
    month: date  # first day of the month
    spent_cents: int  # positive number
    income_cents: int
    net_cents: int  # income - spent
    previous_spent_cents: int
    change_pct: float | None  # spending vs the month before; None if that month had none


class ReimbursementSummary(BaseModel):
    waiting_cents: int  # still owed to me, across all reimbursable purchases (positive)
    count: int  # how many reimbursable purchases aren't fully paid back yet


class AccountActivity(BaseModel):
    """One account's month as its bank shows it: every transaction, transfers included, so
    the numbers can be checked against the bank statement."""

    id: int
    name: str
    institution: str
    type: str
    money_in_cents: int  # this month, positive
    money_out_cents: int  # this month, positive
    count: int  # transactions this month
    first_date: date | None  # the oldest transaction imported, any month
    last_date: date | None  # the newest transaction imported, any month


class ImportResult(BaseModel):
    inserted: int
    skipped: int


class PlaidStatus(BaseModel):
    """Whether Plaid is set up, so the page can explain what's missing instead of failing."""

    configured: bool
    environment: str  # sandbox / production
    problem: str | None  # what's missing, when not configured


class LinkToken(BaseModel):
    link_token: str  # short-lived (about 4 hours); opens Plaid Link once


class PlaidConnect(BaseModel):
    """What Plaid Link hands the browser after you log in to a bank."""

    public_token: str = Field(min_length=1)  # temporary; the backend swaps it for an access token
    institution_name: str = Field(min_length=1, max_length=100)


class PlaidItemOut(BaseModel):
    """A connected bank login. Deliberately leaves out the access token."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    institution_name: str
    environment: str
    status: str
    last_synced_at: datetime | None
    created_at: datetime
