"""Prevent concurrent physical audit-chain forks.

Revision ID: 0002_serialize_physical_audit_chain
Revises: 0001_initial_schema
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_serialize_physical_audit_chain"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The unique predecessor prevents two events from claiming the same chain
    # head even if an unreviewed writer bypasses the application advisory lock.
    # Existing forks intentionally make this migration fail for investigation.
    op.create_index(
        "ix_physicalcontrolevent_previous_hash",
        "physicalcontrolevent",
        ["previous_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_physicalcontrolevent_previous_hash",
        table_name="physicalcontrolevent",
    )
