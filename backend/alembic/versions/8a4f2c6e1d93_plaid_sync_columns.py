"""plaid sync columns

Revision ID: 8a4f2c6e1d93
Revises: 5c1d9e2a7b80
Create Date: 2026-11-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a4f2c6e1d93"
down_revision: str | Sequence[str] | None = "5c1d9e2a7b80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("accounts", sa.Column("plaid_item_id", sa.Integer(), nullable=True))
    op.add_column("accounts", sa.Column("plaid_account_id", sa.String(100), nullable=True))
    op.add_column("accounts", sa.Column("csv_cutoff_date", sa.Date(), nullable=True))
    op.create_foreign_key(
        "accounts_plaid_item_id_fkey",
        "accounts",
        "plaid_items",
        ["plaid_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("accounts_plaid_account_id_key", "accounts", ["plaid_account_id"])

    op.add_column("transactions", sa.Column("plaid_transaction_id", sa.String(100), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("pending", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_unique_constraint(
        "transactions_plaid_transaction_id_key", "transactions", ["plaid_transaction_id"]
    )

    # A database row lock now stops two syncs of one login running at once (see
    # app/services/plaid_sync.py). Unlike a flag, a lock can't get stuck if a sync crashes.
    op.drop_column("plaid_items", "syncing")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "plaid_items",
        sa.Column("syncing", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_constraint("transactions_plaid_transaction_id_key", "transactions")
    op.drop_column("transactions", "pending")
    op.drop_column("transactions", "plaid_transaction_id")
    op.drop_constraint("accounts_plaid_account_id_key", "accounts")
    op.drop_constraint("accounts_plaid_item_id_fkey", "accounts")
    op.drop_column("accounts", "csv_cutoff_date")
    op.drop_column("accounts", "plaid_account_id")
    op.drop_column("accounts", "plaid_item_id")
