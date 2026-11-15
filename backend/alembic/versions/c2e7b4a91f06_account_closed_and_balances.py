"""account closed date and balances

Revision ID: c2e7b4a91f06
Revises: 8a4f2c6e1d93
Create Date: 2026-11-14 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2e7b4a91f06"
down_revision: str | Sequence[str] | None = "8a4f2c6e1d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("accounts", sa.Column("closed_on", sa.Date(), nullable=True))
    op.add_column("accounts", sa.Column("balance_cents", sa.Integer(), nullable=True))
    op.add_column(
        "accounts", sa.Column("balance_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("accounts", "balance_updated_at")
    op.drop_column("accounts", "balance_cents")
    op.drop_column("accounts", "closed_on")
