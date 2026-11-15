"""paychecks: income sources, paycheck rules, manual paycheck marks

Revision ID: f7c9a2e4b6d8
Revises: e5b3c8d2a7f1
Create Date: 2026-11-15 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7c9a2e4b6d8"
down_revision: str | Sequence[str] | None = "e5b3c8d2a7f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "income_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("match_text", sa.String(length=100), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "paycheck_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bucket_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("percent", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bucket_id"], ["buckets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(kind = 'fixed' AND amount_cents > 0 AND percent IS NULL) OR "
            "(kind = 'percent' AND percent BETWEEN 1 AND 100 AND amount_cents IS NULL)",
            name="paycheck_rules_value",
        ),
    )
    op.add_column("transactions", sa.Column("paycheck_override", sa.Boolean(), nullable=True))
    op.create_index(
        "ix_allocations_source_transaction_id", "allocations", ["source_transaction_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_allocations_source_transaction_id", table_name="allocations")
    op.drop_column("transactions", "paycheck_override")
    op.drop_table("paycheck_rules")
    op.drop_table("income_sources")
