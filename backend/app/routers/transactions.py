from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Transaction
from app.schemas import RecategorizeResult, TransactionOut, TransactionUpdate
from app.services.categories import apply_rules

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.patch("/{transaction_id}")
def update_transaction(
    transaction_id: int,
    update: TransactionUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> TransactionOut:
    """Fix a category or transfer flag by hand. Rules and detection won't change it back."""
    t = session.get(Transaction, transaction_id)
    if t is None:
        raise HTTPException(404, f"no transaction with id {transaction_id}")

    if update.category is not None:
        t.category = update.category
        t.category_source = "manual"

    if update.is_transfer is not None:
        t.is_transfer = update.is_transfer
        t.transfer_source = "manual"
        if not update.is_transfer and t.transfer_pair_id is not None:
            # "Not a transfer" means the other side isn't one either. The other side stays
            # "auto", so detection may still pair it with something else later.
            partner = session.get(Transaction, t.transfer_pair_id)
            if partner is not None:
                partner.is_transfer = False
                partner.transfer_pair_id = None
            t.transfer_pair_id = None

    session.commit()
    return TransactionOut.model_validate(t)


@router.post("/recategorize")
def recategorize(session: Annotated[Session, Depends(get_session)]) -> RecategorizeResult:
    """Re-apply the category rule files to every row you haven't categorized by hand."""
    try:
        changed = apply_rules(session)
    except ValueError as e:  # a typo in a rules file
        raise HTTPException(400, str(e)) from None
    session.commit()
    return RecategorizeResult(changed=changed)
