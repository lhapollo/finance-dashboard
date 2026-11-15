from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Account
from app.schemas import AccountOut, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def list_accounts(session: SessionDep) -> list[AccountOut]:
    """Open accounts first, then closed ones."""
    accounts = session.scalars(select(Account).order_by(Account.closed_on.is_not(None), Account.id))
    return [AccountOut.model_validate(a) for a in accounts]


@router.patch("/{account_id}")
def update_account(account_id: int, body: AccountUpdate, session: SessionDep) -> AccountOut:
    """Close an account (closed_on: a date) or reopen it (closed_on: null)."""
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no account with id {account_id}")
    if "closed_on" in body.model_fields_set:
        account.closed_on = body.closed_on
    session.commit()
    return AccountOut.model_validate(account)
