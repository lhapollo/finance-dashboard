"""create plaid_items

Revision ID: 5c1d9e2a7b80
Revises: ff3560534540
Create Date: 2026-11-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c1d9e2a7b80"
down_revision: str | Sequence[str] | None = "ff3560534540"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "plaid_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.String(length=100), nullable=False),
        sa.Column("institution_name", sa.String(length=100), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="ok", nullable=False),
        sa.Column("syncing", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("plaid_items")
