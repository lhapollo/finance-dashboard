"""seed tangerine savings account

Revision ID: 459ef8636f52
Revises: b7e3a91c4d20
Create Date: 2026-11-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "459ef8636f52"
down_revision: str | Sequence[str] | None = "b7e3a91c4d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACCOUNT = {"name": "Tangerine Savings", "institution": "Tangerine", "type": "savings"}


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
