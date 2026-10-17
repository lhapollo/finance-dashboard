from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StandardTransaction(BaseModel):
    """The one format every importer must output. The rest of the app only sees this."""

    model_config = ConfigDict(frozen=True)

    date: date
    description: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    source: Literal["csv", "plaid"] = "csv"

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("description is blank")
        return v

    @field_validator("amount")
    @classmethod
    def nonzero(cls, v: Decimal) -> Decimal:
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
    description: str
    amount: Decimal
    category: str
    category_source: str
    is_transfer: bool


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int


class TransactionUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=50)
    is_transfer: bool | None = None


class CategoryTotal(BaseModel):
    category: str
    total: Decimal  # positive number = amount spent


class PeriodTotal(BaseModel):
    period: date  # first day of the month
    total: Decimal


class ImportResult(BaseModel):
    inserted: int
    skipped: int
