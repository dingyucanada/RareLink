"""Add physical DP privacy budget ledger.

Revision ID: 0005_add_privacy_budget_ledger
Revises: 0004_revoke_physical_approvals
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_add_privacy_budget_ledger"
down_revision: str | None = "0004_revoke_physical_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "physicalfederationjob",
        sa.Column("global_model_signature", sa.String(), nullable=True),
    )
    op.add_column(
        "physicalfederationjob",
        sa.Column(
            "model_signing_key_fingerprint_sha256",
            sa.String(),
            nullable=True,
        ),
    )
    op.add_column(
        "physicalfederationjob",
        sa.Column("model_release_manifest_sha256", sa.String(), nullable=True),
    )
    op.add_column(
        "physicalfederationjob",
        sa.Column("model_released_at", sa.DateTime(), nullable=True),
    )
    for column in (
        "model_signing_key_fingerprint_sha256",
        "model_release_manifest_sha256",
        "model_released_at",
    ):
        op.create_index(
            f"ix_physicalfederationjob_{column}",
            "physicalfederationjob",
            [column],
            unique=False,
        )

    op.create_table(
        "physicalprivacybudget",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("contract_sha256", sa.String(), nullable=False),
        sa.Column("max_epsilon", sa.Float(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("consumed_epsilon", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("ledger_head_sha256", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["physicalfederationjob.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_physicalprivacybudget_job_id",
        "physicalprivacybudget",
        ["job_id"],
        unique=True,
    )
    for column in ("contract_sha256", "status", "created_at", "updated_at"):
        op.create_index(
            f"ix_physicalprivacybudget_{column}",
            "physicalprivacybudget",
            [column],
            unique=False,
        )

    op.create_table(
        "physicalprivacyspend",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("budget_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("cumulative_epsilon", sa.Float(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("accountant", sa.String(), nullable=False),
        sa.Column("optimizer_steps", sa.Integer(), nullable=False),
        sa.Column("previous_hash", sa.String(), nullable=False),
        sa.Column("receipt_sha256", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["physicalprivacybudget.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["physicalfederationjob.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["physicalsite.site_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "budget_id",
            "site_id",
            "round_number",
            name="uq_privacy_spend_site_round",
        ),
    )
    for column in (
        "budget_id",
        "job_id",
        "site_id",
        "round_number",
        "created_at",
    ):
        op.create_index(
            f"ix_physicalprivacyspend_{column}",
            "physicalprivacyspend",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_physicalprivacyspend_receipt_sha256",
        "physicalprivacyspend",
        ["receipt_sha256"],
        unique=True,
    )
def downgrade() -> None:
    op.drop_table("physicalprivacyspend")
    op.drop_table("physicalprivacybudget")
    for column in (
        "model_released_at",
        "model_release_manifest_sha256",
        "model_signing_key_fingerprint_sha256",
    ):
        op.drop_index(
            f"ix_physicalfederationjob_{column}",
            table_name="physicalfederationjob",
        )
    op.drop_column("physicalfederationjob", "model_released_at")
    op.drop_column("physicalfederationjob", "model_release_manifest_sha256")
    op.drop_column(
        "physicalfederationjob",
        "model_signing_key_fingerprint_sha256",
    )
    op.drop_column("physicalfederationjob", "global_model_signature")
