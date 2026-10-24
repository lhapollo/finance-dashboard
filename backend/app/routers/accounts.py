from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Account
from app.schemas import AccountOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("")
def list_accounts(session: Annotated[Session, Depends(get_session)]) -> list[AccountOut]:
    return [
        AccountOut.model_validate(a) for a in session.scalars(select(Account).order_by(Account.id))
    ]
