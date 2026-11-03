"""seed tangerine chequing account

Revision ID: 9f896941e06b
Revises: 36ef1f885d47
Create Date: 2026-10-29 23:45:33.046476

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f896941e06b"
down_revision: str | Sequence[str] | None = "36ef1f885d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACCOUNT = {"name": "Tangerine Chequing", "institution": "Tangerine", "type": "chequing"}


def upgrade() -> None:
    """Upgrade schema."""
    accounts = sa.table(
        "accounts",
        sa.column("name", sa.String),
        sa.column("institution", sa.String),
        sa.column("type", sa.String),
    )
    op.bulk_insert(accounts, [ACCOUNT])


def downgrade() -> None:
    """Downgrade schema."""
    # Its transactions go first, or the foreign key would block deleting the account.
    op.execute(
        sa.text(
            "DELETE FROM transactions WHERE account_id = "
            "(SELECT id FROM accounts WHERE name = :name)"
        ).bindparams(name=ACCOUNT["name"])
    )
    op.execute(sa.text("DELETE FROM accounts WHERE name = :name").bindparams(name=ACCOUNT["name"]))
