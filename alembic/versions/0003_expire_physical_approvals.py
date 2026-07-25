"""Persist expiry for physical contract second approvals.

Revision ID: 0003_expire_physical_approvals
Revises: 0002_serialize_physical_audit_chain
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_expire_physical_approvals"
down_revision: str | None = "0002_serialize_physical_audit_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable is deliberate: approvals created before this revision fail
    # closed and are never assigned a fabricated expiry during migration.
    op.add_column(
        "physicalfederationjob",
        sa.Column("second_approval_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_physicalfederationjob_second_approval_expires_at",
        "physicalfederationjob",
        ["second_approval_expires_at"],
        unique=False,
    )
    op.add_column(
        "physicaljobapprovalrecord",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_physicaljobapprovalrecord_expires_at",
        "physicaljobapprovalrecord",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_physicaljobapprovalrecord_expires_at",
        table_name="physicaljobapprovalrecord",
    )
    op.drop_column("physicaljobapprovalrecord", "expires_at")
    op.drop_index(
        "ix_physicalfederationjob_second_approval_expires_at",
        table_name="physicalfederationjob",
    )
    op.drop_column("physicalfederationjob", "second_approval_expires_at")
