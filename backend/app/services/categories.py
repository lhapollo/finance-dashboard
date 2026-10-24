"""Rule-based categories: 'description contains X' -> category, read from YAML files."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.models import Transaction

UNCATEGORIZED = "uncategorized"

# Generic rules (chains, keywords) are committed. Personal ones, like local restaurants that
# would show where I live, stay in the gitignored data/ folder and win over generic ones.
DEFAULT_RULES = Path(__file__).resolve().parents[1] / "category_rules.yaml"
PERSONAL_RULES = DATA_DIR / "category_rules.yaml"


@dataclass(frozen=True)
class Rule:
    pattern: str
    category: str
    regex: re.Pattern
    priority: int  # higher wins a tie; personal rules beat default ones


def load_rules(paths: list[Path] | None = None) -> list[Rule]:
    """Read rule files shaped like {category: [pattern, ...]}. Missing files are skipped."""
    paths = paths if paths is not None else [DEFAULT_RULES, PERSONAL_RULES]
    rules = []
    for priority, path in enumerate(paths):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected 'category: [patterns]' entries")
        for category, patterns in data.items():
            if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
                raise ValueError(f"{path}: '{category}' should be a list of text patterns")
            for p in patterns:
                rules.append(Rule(p, str(category).lower(), _compile(p), priority))
    return rules


def _compile(pattern: str) -> re.Pattern:
    """Whole words only, so TEA doesn't match STEAM. A trailing * also matches longer words,
    for banks that glue names together: DOORDASH* matches DD/DOORDASHYOSUSHI."""
    prefix = pattern.endswith("*")
    body = re.escape(pattern.rstrip("*").strip())
    end = "" if prefix else r"(?![A-Za-z0-9])"
    return re.compile(rf"(?<![A-Za-z0-9]){body}{end}", re.IGNORECASE)


def categorize(raw_description: str, rules: list[Rule]) -> str:
    """The longest matching pattern wins, so 'WUSA'S ONLINE SHOP' beats 'WUSA' without
    having to keep the file in any particular order."""
    matches = [r for r in rules if r.regex.search(raw_description)]
    if not matches:
        return UNCATEGORIZED
    return max(matches, key=lambda r: (len(r.pattern.rstrip("*")), r.priority)).category


def apply_rules(session: Session, rules: list[Rule] | None = None) -> int:
    """Re-categorize every row the rules own; returns how many changed.

    Rows you categorized by hand (category_source = "manual") are never touched, so editing
    the rule files and re-running this is always safe.
    """
    rules = rules if rules is not None else load_rules()
    changed = 0
    for t in session.scalars(select(Transaction).where(Transaction.category_source == "rule")):
        category = categorize(t.raw_description, rules)
        if t.category != category:
            t.category = category
            changed += 1
    return changed
