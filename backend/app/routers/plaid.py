"""Connecting banks through Plaid Link.

The flow, start to finish:
1. The browser asks for a link token (POST /plaid/link-token). It opens Plaid Link, the
   login pop-up, which only works with a fresh link token from our backend.
2. You log in to your bank inside Plaid Link. Your bank password goes to Plaid, never to us.
3. Plaid Link hands the browser a temporary public token, which it sends to POST /plaid/items.
4. The backend swaps the public token for a permanent access token, encrypts it and saves it.
   The access token never leaves the backend.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_session
from app.models import PlaidItem
from app.plaid import PlaidClient, PlaidError, PlaidNotConfigured, get_plaid
from app.schemas import LinkToken, PlaidConnect, PlaidItemOut, PlaidStatus
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
def create_link_token(plaid: PlaidDep) -> LinkToken:
    data = plaid.post(
        "/link/token/create",
        {
            "client_name": "Finance Dashboard",
            "language": "en",
            "country_codes": ["CA"],
            "products": ["transactions"],
            # Plaid wants an id for "the user". There's only one: me.
            "user": {"client_user_id": "me"},
            # Ask for as much history as Plaid allows (2 years) on the first sync.
            "transactions": {"days_requested": 730},
        },
    )
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

    session.delete(item)
    session.commit()
