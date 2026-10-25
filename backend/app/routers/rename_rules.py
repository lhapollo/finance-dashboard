from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import RenameRule
from app.schemas import RenameRuleOut
from app.services.renames import apply_renames

router = APIRouter(prefix="/rename-rules", tags=["rename rules"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def list_rename_rules(session: SessionDep) -> list[RenameRuleOut]:
    """Every merchant rename. Create one with PATCH /transactions/{id} and rename_all."""
    rules = session.scalars(select(RenameRule).order_by(RenameRule.match))
    return [RenameRuleOut.model_validate(r) for r in rules]


@router.delete("/{rule_id}", status_code=204)
def delete_rename_rule(rule_id: int, session: SessionDep) -> None:
    """Stop renaming that merchant; its transactions go back to the converter's name."""
    rule = session.get(RenameRule, rule_id)
    if rule is None:
        raise HTTPException(404, f"no rename rule with id {rule_id}")
    session.delete(rule)
    session.flush()
    apply_renames(session)
    session.commit()
