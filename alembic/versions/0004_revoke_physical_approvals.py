"""Add immutable physical approval revocation records.

Revision ID: 0004_revoke_physical_approvals
Revises: 0003_expire_physical_approvals
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_revoke_physical_approvals"
down_revision: str | None = "0003_expire_physical_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "physicalfederationjob",
        sa.Column("second_approval_revocation_id", sa.String(), nullable=True),
    )
    op.add_column(
        "physicalfederationjob",
        sa.Column("second_approval_revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_physicalfederationjob_second_approval_revocation_id",
        "physicalfederationjob",
        ["second_approval_revocation_id"],
        unique=False,
    )
    op.create_index(
        "ix_physicalfederationjob_second_approval_revoked_at",
        "physicalfederationjob",
        ["second_approval_revoked_at"],
        unique=False,
    )
    op.create_table(
        "physicaljobapprovalrevocation",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("contract_sha256", sa.String(), nullable=False),
        sa.Column("revoked_by", sa.String(), nullable=False),
        sa.Column("attestation", sa.String(), nullable=False),
        sa.Column("reason_sha256", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["physicaljobapprovalrecord.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["physicalfederationjob.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "contract_sha256",
        "revoked_by",
        "created_at",
    ):
        op.create_index(
            f"ix_physicaljobapprovalrevocation_{column}",
            "physicaljobapprovalrevocation",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_physicaljobapprovalrevocation_job_id",
        "physicaljobapprovalrevocation",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        "ix_physicaljobapprovalrevocation_approval_id",
        "physicaljobapprovalrevocation",
        ["approval_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("physicaljobapprovalrevocation")
    op.drop_index(
        "ix_physicalfederationjob_second_approval_revoked_at",
        table_name="physicalfederationjob",
    )
    op.drop_index(
        "ix_physicalfederationjob_second_approval_revocation_id",
        table_name="physicalfederationjob",
    )
    op.drop_column("physicalfederationjob", "second_approval_revoked_at")
    op.drop_column("physicalfederationjob", "second_approval_revocation_id")
