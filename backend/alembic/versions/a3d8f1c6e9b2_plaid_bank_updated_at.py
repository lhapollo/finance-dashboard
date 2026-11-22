"""plaid_items.bank_updated_at: when Plaid last got new data from the bank

Revision ID: a3d8f1c6e9b2
Revises: f7c9a2e4b6d8
Create Date: 2026-11-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d8f1c6e9b2"
down_revision: str | Sequence[str] | None = "f7c9a2e4b6d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "plaid_items", sa.Column("bank_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("plaid_items", "bank_updated_at")
