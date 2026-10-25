"""Renaming merchants: one transaction by hand, or every transaction from a merchant by rule."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RenameRule, Transaction


def apply_renames(session: Session) -> int:
    """Set every non-manual row's name from the rename rules; returns how many changed.

    Rows renamed by hand (description_source = "manual") are left alone.
    """
    rules = {r.match: r.name for r in session.scalars(select(RenameRule))}
    changed = 0
    rows = session.scalars(select(Transaction).where(Transaction.description_source != "manual"))
    for t in rows:
        name = rules.get(t.cleaned_description, t.cleaned_description)
        source = "rule" if t.cleaned_description in rules else "auto"
        if (t.description, t.description_source) != (name, source):
            t.description, t.description_source = name, source
            changed += 1
    return changed


def rename_merchant(session: Session, match: str, name: str) -> None:
    """Show every transaction the converter named `match` as `name`, now and in future
    imports. Renaming back to the converter's own name removes the rule."""
    rule = session.scalar(select(RenameRule).where(RenameRule.match == match))
    if name == match:
        if rule is not None:
            session.delete(rule)
    elif rule is None:
        session.add(RenameRule(match=match, name=name))
    else:
        rule.name = name
    session.flush()
    apply_renames(session)
