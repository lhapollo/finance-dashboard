"""add reimburses_id to transactions

Revision ID: b7e3a91c4d20
Revises: 204b291722a9
Create Date: 2026-11-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3a91c4d20"
down_revision: str | Sequence[str] | None = "204b291722a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("transactions", sa.Column("reimburses_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_transactions_reimburses_id"), "transactions", ["reimburses_id"], unique=False
    )
    op.create_foreign_key(
        "fk_transactions_reimburses_id",
        "transactions",
        "transactions",
        ["reimburses_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_transactions_reimburses_id", "transactions", type_="foreignkey")
    op.drop_index(op.f("ix_transactions_reimburses_id"), table_name="transactions")
    op.drop_column("transactions", "reimburses_id")
