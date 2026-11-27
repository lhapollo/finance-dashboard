"""transactions.note: a note I write on a transaction

Revision ID: b4e9d2f7a1c3
Revises: a3d8f1c6e9b2
Create Date: 2026-11-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e9d2f7a1c3"
down_revision: str | Sequence[str] | None = "a3d8f1c6e9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("transactions", sa.Column("note", sa.String(500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transactions", "note")
