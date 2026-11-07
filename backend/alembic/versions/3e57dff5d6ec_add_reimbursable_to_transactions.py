"""add reimbursable to transactions

Revision ID: 3e57dff5d6ec
Revises: 459ef8636f52
Create Date: 2026-11-07 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3e57dff5d6ec"
down_revision: str | Sequence[str] | None = "459ef8636f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transactions",
        sa.Column("reimbursable", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transactions", "reimbursable")
