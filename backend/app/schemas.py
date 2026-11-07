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
    """

    category: str | None = Field(default=None, min_length=1, max_length=50)
    is_transfer: bool | None = None
    description: str | None = Field(default=None, max_length=500)
    rename_all: bool = False
    reimburses_id: int | None = None

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
        # "Dining " and "dining" should be one category, not two.
        if v is not None:
            v = " ".join(v.split()).lower()
            if not v:
                raise ValueError("category is blank")
        return v


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


class ImportResult(BaseModel):
    inserted: int
    skipped: int
