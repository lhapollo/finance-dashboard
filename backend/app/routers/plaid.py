"""Connecting banks through Plaid Link.

The flow, start to finish:
1. The browser asks for a link token (POST /plaid/link-token). It opens Plaid Link, the
   login pop-up, which only works with a fresh link token from our backend.
2. You log in to your bank inside Plaid Link. Your bank password goes to Plaid, never to us.
3. Plaid Link hands the browser a temporary public token, which it sends to POST /plaid/items.
4. The backend swaps the public token for a permanent access token, encrypts it and saves it.
   The access token never leaves the backend.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.db import get_session
from app.models import Account, PlaidItem, Transaction
from app.plaid import PlaidClient, PlaidError, PlaidNotConfigured, get_plaid
from app.schemas import (
    LinkToken,
    PlaidAccountLinks,
    PlaidAccountOut,
    PlaidConnect,
    PlaidItemOut,
    PlaidStatus,
    SyncResultOut,
)
from app.services.plaid_sync import is_stale, sync_item
from app.services.secrets import TokenKeyError, decrypt_token, encrypt_token, require_token_key

router = APIRouter(prefix="/plaid", tags=["plaid"])

SessionDep = Annotated[Session, Depends(get_session)]
PlaidDep = Annotated[PlaidClient, Depends(get_plaid)]

# Plaid errors that mean "this login is already gone at Plaid", so forgetting it is safe.
_ALREADY_GONE = {"ITEM_NOT_FOUND", "INVALID_ACCESS_TOKEN"}


@router.get("/status")
def plaid_status() -> PlaidStatus:
    try:
        get_plaid()
        require_token_key()
    except (PlaidNotConfigured, TokenKeyError) as e:
        return PlaidStatus(configured=False, environment=config.PLAID_ENV, problem=str(e))
    return PlaidStatus(configured=True, environment=config.PLAID_ENV, problem=None)


@router.post("/link-token")
def create_link_token(
    session: SessionDep, plaid: PlaidDep, item_id: int | None = None
) -> LinkToken:
    """A link token for connecting a new bank, or with `item_id`, for logging in to a
    connected one again ("update mode"), e.g. after the bank asked for a new password. Update
    mode fixes the existing connection instead of adding a second one."""
    body: dict[str, Any] = {
        "client_name": "Finance Dashboard",
        "language": "en",
        "country_codes": ["CA"],
        # Plaid wants an id for "the user". There's only one: me.
        "user": {"client_user_id": "me"},
    }
    if item_id is not None:
        body["access_token"] = decrypt_token(_item_or_404(session, item_id).access_token)
    else:
        body["products"] = ["transactions"]
        # Ask for as much history as Plaid allows (2 years) on the first sync.
        body["transactions"] = {"days_requested": 730}
    data = plaid.post("/link/token/create", body)
    return LinkToken(link_token=data["link_token"])


@router.post("/items", status_code=status.HTTP_201_CREATED)
def connect_bank(body: PlaidConnect, session: SessionDep, plaid: PlaidDep) -> PlaidItemOut:
    # Check the key first, so a missing key can't leave a connected login we couldn't save.
    require_token_key()
    data = plaid.post("/item/public_token/exchange", {"public_token": body.public_token})

    # Logging in to the same bank again gives a new item; the old one keeps working until
    # removed. Remember both, and you can remove the extra one from the Accounts page.
    item = PlaidItem(
        item_id=data["item_id"],
        institution_name=body.institution_name,
        environment=plaid.environment,
        access_token=encrypt_token(data["access_token"]),
    )
    session.add(item)
    session.commit()
    return PlaidItemOut.model_validate(item)


@router.get("/items")
def list_banks(session: SessionDep) -> list[PlaidItemOut]:
    items = session.scalars(select(PlaidItem).order_by(PlaidItem.id))
    return [PlaidItemOut.model_validate(i) for i in items]


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_bank(item_id: int, session: SessionDep) -> None:
    """Disconnect a bank: tell Plaid to delete the login, then forget it here. Transactions
    already imported from it stay."""
    item = session.get(PlaidItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no connected bank with that id")

    if item.environment == "sandbox" and config.PLAID_ENV != "sandbox":
        pass  # a fake sandbox login: nothing real to delete at Plaid, just forget it
    elif item.environment != config.PLAID_ENV:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"this bank was connected in {item.environment}; set PLAID_ENV={item.environment} "
            "in .env to remove it, so Plaid deletes the login too",
        )
    else:
        try:
            token = decrypt_token(item.access_token)
        except TokenKeyError:
            # The key changed, so the token is unreadable and useless. Forget the login here;
            # Plaid's dashboard can still remove it at Plaid's end.
            token = None
        if token is not None:
            try:
                get_plaid().post("/item/remove", {"access_token": token})
            except PlaidError as e:
                if e.code not in _ALREADY_GONE:
                    raise

    # Its accounts go back to CSV imports, with no cutoff.
    for account in item.accounts:
        account.plaid_account_id = None
        account.csv_cutoff_date = None
    session.delete(item)
    session.commit()


# Plaid's account kinds -> ours.
_TYPES = {"credit": "credit", "checking": "chequing", "savings": "savings"}


def _our_type(plaid_account: dict[str, Any]) -> str | None:
    if plaid_account["type"] == "credit":
        return "credit"
    if plaid_account["type"] == "investment":
        return "investment"
    return _TYPES.get(plaid_account.get("subtype") or "")


def _item_or_404(session: Session, item_id: int) -> PlaidItem:
    item = session.get(PlaidItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no connected bank with that id")
    if item.environment != config.PLAID_ENV:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"this bank was connected in {item.environment}, but PLAID_ENV is {config.PLAID_ENV}",
        )
    return item


def _plaid_accounts(plaid: PlaidClient, item: PlaidItem) -> list[dict[str, Any]]:
    return plaid.post("/accounts/get", {"access_token": decrypt_token(item.access_token)})[
        "accounts"
    ]


@router.get("/items/{item_id}/accounts")
def list_bank_accounts(item_id: int, session: SessionDep, plaid: PlaidDep) -> list[PlaidAccountOut]:
    """The accounts in one bank login, each with the account of mine it's linked to or
    looks like (same bank, same kind, and the only one)."""
    item = _item_or_404(session, item_id)
    mine = session.scalars(select(Account).order_by(Account.id)).all()
    linked = {a.plaid_account_id: a.id for a in mine if a.plaid_account_id}
    bank = item.institution_name.lower()

    result = []
    for pa in _plaid_accounts(plaid, item):
        alike = [
            a
            for a in mine
            if a.plaid_account_id is None
            and bank.startswith(a.institution.lower())
            and a.type == _our_type(pa)
        ]
        result.append(
            PlaidAccountOut(
                plaid_account_id=pa["account_id"],
                name=pa.get("official_name") or pa["name"],
                mask=pa.get("mask"),
                type=pa["type"],
                subtype=pa.get("subtype"),
                account_id=linked.get(pa["account_id"]),
                suggested_account_id=alike[0].id if len(alike) == 1 else None,
            )
        )
    return result


@router.put("/items/{item_id}/accounts")
def link_bank_accounts(
    item_id: int, body: PlaidAccountLinks, session: SessionDep, plaid: PlaidDep
) -> list[PlaidAccountOut]:
    """Say which of my accounts each Plaid account is (or None to skip it).

    Linking sets the account's CSV cutoff to its newest CSV transaction: CSV imports cover up
    to that day, Plaid everything after (see app/services/plaid_sync.py for the overlap).
    Any change makes the next sync start from the beginning, so a newly linked account gets
    its whole history; nothing is added twice, since Plaid's ids are remembered.
    """
    item = _item_or_404(session, item_id)
    in_this_bank = {pa["account_id"] for pa in _plaid_accounts(plaid, item)}
    targets = [link.account_id for link in body.links if link.account_id is not None]
    if len(targets) != len(set(targets)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "two bank accounts can't share one account"
        )

    changed = False
    for link in body.links:
        if link.plaid_account_id not in in_this_bank:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{link.plaid_account_id} isn't in this bank"
            )
        current = session.scalar(
            select(Account).where(Account.plaid_account_id == link.plaid_account_id)
        )
        if current is not None and current.id == link.account_id:
            continue  # unchanged
        if current is not None:
            current.plaid_account_id = None
            current.plaid_item_id = None
            current.csv_cutoff_date = None
        if link.account_id is not None:
            account = session.get(Account, link.account_id)
            if account is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no account {link.account_id}")
            if account.plaid_account_id is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{account.name} is already linked to another bank account",
                )
            session.flush()  # the unlinked account frees its plaid_account_id first
            account.plaid_item_id = item.id
            account.plaid_account_id = link.plaid_account_id
            account.csv_cutoff_date = session.scalar(
                select(func.max(Transaction.date)).where(
                    Transaction.account_id == account.id, Transaction.source == "csv"
                )
            )
        changed = True

    if changed:
        item.cursor = None
    session.commit()
    return list_bank_accounts(item_id, session, plaid)


@router.post("/sync")
def sync_banks(session: SessionDep, force: bool = False) -> list[SyncResultOut]:
    """Fetch new transactions from every connected bank. Without `force`, only banks not
    synced in the last few hours, so the dashboard can call this on every visit."""
    now = datetime.now(UTC)
    connected = session.scalars(
        select(PlaidItem).where(PlaidItem.environment == config.PLAID_ENV).order_by(PlaidItem.id)
    )
    items = [i for i in connected if force or is_stale(i, now)]
    if not items:
        return []  # also means no Plaid keys are needed when nothing is connected
    plaid = get_plaid()
    return [
        SyncResultOut.model_validate(sync_item(session, plaid, item.id), from_attributes=True)
        for item in items
    ]
