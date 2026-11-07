"""create transaction_splits

Revision ID: ff3560534540
Revises: 3e57dff5d6ec
Create Date: 2026-11-07 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff3560534540"
down_revision: str | Sequence[str] | None = "3e57dff5d6ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "transaction_splits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("reimburses_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reimburses_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_transaction_splits_transaction_id"), "transaction_splits", ["transaction_id"]
    )
    op.create_index(
        op.f("ix_transaction_splits_reimburses_id"), "transaction_splits", ["reimburses_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_transaction_splits_reimburses_id"), table_name="transaction_splits")
    op.drop_index(op.f("ix_transaction_splits_transaction_id"), table_name="transaction_splits")
    op.drop_table("transaction_splits")
