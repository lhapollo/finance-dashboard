from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    closed_on: date | None


class AccountUpdate(BaseModel):
    """Fields I can change on an account. Leave a field out to keep it as is."""

    closed_on: date | None = None  # null reopens it


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
    # Set only when I picked the bucket by hand (bucket_assigned_by = "manual"); otherwise
    # the category's default bucket applies.
    bucket_id: int | None
    bucket_assigned_by: str | None
    note: str | None  # a note I wrote on it
    source: str  # csv / plaid
    pending: bool  # Plaid only: not final yet, the amount can still change
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
    # The bucket this spending comes out of, picked by hand (null: no bucket). Send
    # bucket_auto: true instead to go back to the category's default bucket.
    bucket_id: int | None = None
    bucket_auto: bool = False
    # A note on this transaction. Send null or "" to remove it.
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def tidy_note(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

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
    plaid_linked: bool  # new transactions come from Plaid, not CSVs
    closed_on: date | None
    balance_cents: int | None  # from the bank via Plaid; negative = owed
    balance_updated_at: datetime | None


class BalanceSummary(BaseModel):
    """Money I have right now, from the balances Plaid reports. Closed accounts are left out.

    available = cash - owed: money on credit cards is already spent, so the cash that will
    pay those cards off isn't free to spend again.
    """

    cash_cents: int  # chequing + savings
    owed_cents: int  # on credit cards (positive)
    available_cents: int
    # The oldest balance used, so the page can say how fresh the total is.
    as_of: datetime | None
    # Open accounts with no balance (not linked to Plaid), so not in the totals.
    missing: list[str]


class ImportResult(BaseModel):
    inserted: int
    skipped: int  # already imported, or from_plaid
    # Of the skipped: rows Plaid already brought in (same date and amount).
    from_plaid: int = 0


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
    bank_updated_at: datetime | None
    created_at: datetime


class PlaidAccountOut(BaseModel):
    """One account inside a connected bank login, and which of my accounts it's linked to."""

    plaid_account_id: str
    name: str
    mask: str | None  # last 4 digits
    type: str  # Plaid's words: depository / credit / ...
    subtype: str | None  # checking / savings / credit card / ...
    account_id: int | None  # my account it's linked to
    suggested_account_id: int | None  # my account it looks like, when not linked yet


class PlaidAccountLink(BaseModel):
    plaid_account_id: str
    account_id: int | None  # None = don't import this one


class PlaidAccountLinks(BaseModel):
    links: list[PlaidAccountLink]


class SyncResultOut(BaseModel):
    item_id: int
    institution_name: str
    added: int
    matched: int  # already imported from a CSV, so not added again
    updated: int
    removed: int
    unlinked_accounts: list[str]
    error: str | None


class BucketIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["recurring", "goal"]
    target_amount_cents: int | None = Field(default=None, gt=0, strict=True)
    target_date: date | None = None
    # Make this the category's default bucket (the "Make a bucket" button on a category).
    # Without it, a bucket named like a category still becomes its default; see
    # services/budget.py link_matching_category.
    category: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def tidy_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is blank")
        return v


class BucketUpdate(BaseModel):
    """Leave a field out to keep it as is."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    target_amount_cents: int | None = Field(default=None, gt=0, strict=True)
    target_date: date | None = None
    archived: bool | None = None


class BucketOut(BaseModel):
    id: int
    name: str
    type: str
    target_amount_cents: int | None
    target_date: date | None
    archived: bool
    allocated_cents: int  # put in, minus taken out, since the budget started
    spent_cents: int  # spending out of it since the budget started (refunds lower it)
    balance_cents: int  # allocated - spent: what's left in it now
    progress_pct: int | None  # goals: balance as a % of the target (0-100)


class BudgetOut(BaseModel):
    """The whole budget: every bucket, and the money no bucket has claimed yet."""

    start_date: date | None  # None until the fresh-start setup is done
    available_cents: int | None  # cash minus card debt, from bank balances (None: unknown)
    available_as_of: datetime | None
    assigned_cents: int  # in buckets
    # available - assigned. None when available is unknown. Negative means more is in
    # buckets than you actually have.
    unassigned_cents: int | None
    # Spending since the start that no bucket covers (its category has no bucket). It still
    # lowers available money, so it comes out of unassigned.
    unbucketed_spent_cents: int
    buckets: list[BucketOut]  # open ones first, archived last


class CategoryBucketOut(BaseModel):
    category: str
    bucket_id: int | None  # its default bucket, if it has one
    spent_cents: int  # spending in this category since the budget started


class CategoryBucketIn(BaseModel):
    bucket_id: int | None  # None: no default bucket


class OpeningBalance(BaseModel):
    bucket_id: int
    amount_cents: int = Field(ge=0, strict=True)


class BudgetStart(BaseModel):
    """The fresh start: from this date, split the money I have across buckets."""

    start_date: date
    opening: list[OpeningBalance]


class AssignIn(BaseModel):
    """Put unassigned money into a bucket (positive) or give some back (negative)."""

    bucket_id: int
    amount_cents: int = Field(strict=True)
    note: str | None = Field(default=None, max_length=200)


class MoveIn(BaseModel):
    """Move money from one bucket to another, e.g. to cover overspent groceries."""

    from_bucket_id: int
    to_bucket_id: int
    amount_cents: int = Field(gt=0, strict=True)
    note: str | None = Field(default=None, max_length=200)


class IncomeSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    account_id: int
    match_text: str = Field(min_length=2, max_length=100)
    active: bool = True

    @field_validator("name", "match_text")
    @classmethod
    def tidy(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("is blank")
        return v


class IncomeSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    account_id: int
    match_text: str
    active: bool


class IncomeSourceSuggestion(BaseModel):
    """A deposit that keeps showing up as income: probably a paycheck."""

    account_id: int
    match_text: str  # the deposit's cleaned-up name, e.g. "Rippling Canada"
    count: int  # how many times it came in
    last_date: date
    last_amount_cents: int


class PaycheckRuleIn(BaseModel):
    bucket_id: int
    kind: Literal["fixed", "percent"]
    amount_cents: int | None = Field(default=None, gt=0, strict=True)  # fixed
    percent: int | None = Field(default=None, ge=1, le=100, strict=True)  # percent

    @model_validator(mode="after")
    def one_value(self) -> "PaycheckRuleIn":
        if self.kind == "fixed" and (self.amount_cents is None or self.percent is not None):
            raise ValueError("a fixed rule needs amount_cents (and no percent)")
        if self.kind == "percent" and (self.percent is None or self.amount_cents is not None):
            raise ValueError("a percent rule needs percent (and no amount_cents)")
        return self


class PaycheckRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bucket_id: int
    kind: str
    amount_cents: int | None
    percent: int | None


class BucketAmount(BaseModel):
    bucket_id: int
    amount_cents: int = Field(ge=0, strict=True)


class PaycheckOut(BaseModel):
    transaction_id: int
    date: date
    description: str
    account_id: int
    deposit_cents: int  # the whole deposit
    # The part that's pay: the whole deposit, or a split deposit's income parts (a work
    # reimbursement that came with the pay isn't pay).
    paycheck_cents: int
    detected: bool  # an income source recognizes it
    override: bool | None  # what I said by hand, if anything
    is_paycheck: bool
    # Can be split into buckets: on or after the budget start. Earlier paychecks were
    # already in the money the fresh start split up.
    splittable: bool
    split: list[BucketAmount]  # what's been put into buckets from it
    split_cents: int


class PaycheckSplitSuggestion(BaseModel):
    paycheck_cents: int
    suggested: list[BucketAmount]  # from the paycheck rules
    leftover_cents: int  # what the rules leave unassigned


class PaycheckMark(BaseModel):
    is_paycheck: bool | None  # None: back to detection


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(max_length=4000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class AskStep(BaseModel):
    tool: str
    arguments: dict
    result: dict


class AskOut(BaseModel):
    answer: str
    steps: list[AskStep]  # the tools used, so you can check where numbers came from
