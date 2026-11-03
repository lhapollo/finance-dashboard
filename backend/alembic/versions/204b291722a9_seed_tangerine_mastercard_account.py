"""seed tangerine mastercard account

Revision ID: 204b291722a9
Revises: 9f896941e06b
Create Date: 2026-11-03 00:11:10.134546

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "204b291722a9"
down_revision: str | Sequence[str] | None = "9f896941e06b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACCOUNT = {"name": "Tangerine Mastercard", "institution": "Tangerine", "type": "credit"}


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
