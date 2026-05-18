"""merge_terminal_reports_and_canonical

Merge the terminal-reports branch with the canonical/batch4 branch:
  - c2a4f9df1b10 (create_terminal_reports)
  - f1a4c9e2b8d3 (canonical/batch4 chain, including c2a8f1f4a9c3)

This revision has no schema changes — it exists solely to reunify the
migration graph so that there is exactly one head going forward.

Revision ID: d0e1f2a3b4c5
Revises: c2a4f9df1b10, f1a4c9e2b8d3
Create Date: 2026-05-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = ('c2a4f9df1b10', 'f1a4c9e2b8d3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No schema changes — merge only.
    pass


def downgrade() -> None:
    # No schema changes to revert.
    pass
