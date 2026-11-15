"""spending from buckets: category defaults and per-transaction overrides

Revision ID: e5b3c8d2a7f1
Revises: d4a1f7c3e852
Create Date: 2026-11-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b3c8d2a7f1"
down_revision: str | Sequence[str] | None = "d4a1f7c3e852"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "category_buckets",
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("bucket_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bucket_id"], ["buckets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("category"),
    )
    op.add_column("transactions", sa.Column("bucket_id", sa.Integer(), nullable=True))
    op.add_column(
        "transactions", sa.Column("bucket_assigned_by", sa.String(length=10), nullable=True)
    )
    op.create_foreign_key(
        "transactions_bucket_id_fkey",
        "transactions",
        "buckets",
        ["bucket_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("transactions_bucket_id_fkey", "transactions")
    op.drop_column("transactions", "bucket_assigned_by")
    op.drop_column("transactions", "bucket_id")
    op.drop_table("category_buckets")
