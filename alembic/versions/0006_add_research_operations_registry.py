"""Add multi-study operations and signed model/evidence registries.

Revision ID: 0006_add_research_operations_registry
Revises: 0005_add_privacy_budget_ledger
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_add_research_operations_registry"
down_revision: str | None = "0005_add_privacy_budget_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "study",
        sa.Column(
            "organization_id",
            sa.String(),
            nullable=False,
            server_default="rarelink-demo",
        ),
    )
    op.add_column(
        "study",
        sa.Column("created_by", sa.String(), nullable=False, server_default="researcher"),
    )
    op.add_column(
        "study",
        sa.Column(
            "participating_sites_json",
            sa.String(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "study",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_study_organization_id", "study", ["organization_id"], unique=False)
    op.create_index("ix_study_created_by", "study", ["created_by"], unique=False)

    op.create_table(
        "studysitemembership",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("organization", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("data_use_approved", sa.Boolean(), nullable=False),
        sa.Column("certificate_bound", sa.Boolean(), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(), nullable=True),
        sa.Column("invited_by", sa.String(), nullable=False),
        sa.Column("activated_by", sa.String(), nullable=True),
        sa.Column("reason_sha256", sa.String(), nullable=True),
        *_timestamps(),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["study_id"], ["study.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "site_id", name="uq_study_site_membership"),
    )
    for column in (
        "study_id",
        "site_id",
        "organization",
        "status",
        "dataset_fingerprint",
        "invited_by",
        "activated_by",
        "created_at",
        "updated_at",
        "activated_at",
        "withdrawn_at",
    ):
        op.create_index(
            f"ix_studysitemembership_{column}",
            "studysitemembership",
            [column],
            unique=False,
        )

    op.create_table(
        "evidencepackagerecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("package_sha256", sa.String(), nullable=False),
        sa.Column("manifest_sha256", sa.String(), nullable=False),
        sa.Column("model_sha256", sa.String(), nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        sa.Column("signing_key_fingerprint_sha256", sa.String(), nullable=False),
        sa.Column("validation_tier", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("site_count", sa.Integer(), nullable=False),
        sa.Column("required_quorum", sa.Integer(), nullable=False),
        sa.Column("privacy_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("security_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("dual_approval_distinct", sa.Boolean(), nullable=False),
        sa.Column("contains_sensitive_data", sa.Boolean(), nullable=False),
        sa.Column("verifier_version", sa.String(), nullable=False),
        sa.Column("registered_by", sa.String(), nullable=False),
        sa.Column("verified_by", sa.String(), nullable=True),
        sa.Column("released_by", sa.String(), nullable=True),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.Column("reason_sha256", sa.String(), nullable=True),
        *_timestamps(),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["study_id"], ["study.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidencepackagerecord_package_sha256",
        "evidencepackagerecord",
        ["package_sha256"],
        unique=True,
    )
    op.create_index(
        "ix_evidencepackagerecord_manifest_sha256",
        "evidencepackagerecord",
        ["manifest_sha256"],
        unique=True,
    )
    for column in (
        "study_id",
        "model_sha256",
        "signing_key_fingerprint_sha256",
        "validation_tier",
        "status",
        "registered_by",
        "verified_by",
        "released_by",
        "revoked_by",
        "created_at",
        "updated_at",
        "verified_at",
        "released_at",
        "revoked_at",
    ):
        op.create_index(
            f"ix_evidencepackagerecord_{column}",
            "evidencepackagerecord",
            [column],
            unique=False,
        )

    op.create_table(
        "modelversion",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("semantic_version", sa.String(), nullable=False),
        sa.Column("model_family", sa.String(), nullable=False),
        sa.Column("artifact_sha256", sa.String(), nullable=False),
        sa.Column("source_job_id", sa.String(), nullable=True),
        sa.Column("evidence_package_id", sa.String(), nullable=True),
        sa.Column("validation_tier", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metrics_json", sa.String(), nullable=False),
        sa.Column("signature", sa.String(), nullable=True),
        sa.Column("signing_key_fingerprint_sha256", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("released_by", sa.String(), nullable=True),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.Column("reason_sha256", sa.String(), nullable=True),
        *_timestamps(),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["study_id"], ["study.id"]),
        sa.ForeignKeyConstraint(["evidence_package_id"], ["evidencepackagerecord.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "study_id",
            "name",
            "semantic_version",
            name="uq_model_version_study_name_version",
        ),
    )
    for column in (
        "study_id",
        "name",
        "semantic_version",
        "model_family",
        "artifact_sha256",
        "source_job_id",
        "evidence_package_id",
        "validation_tier",
        "status",
        "signing_key_fingerprint_sha256",
        "created_by",
        "approved_by",
        "released_by",
        "revoked_by",
        "created_at",
        "updated_at",
        "approved_at",
        "released_at",
        "revoked_at",
    ):
        op.create_index(
            f"ix_modelversion_{column}",
            "modelversion",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("modelversion")
    op.drop_table("evidencepackagerecord")
    op.drop_table("studysitemembership")
    op.drop_index("ix_study_created_by", table_name="study")
    op.drop_index("ix_study_organization_id", table_name="study")
    op.drop_column("study", "revision")
    op.drop_column("study", "participating_sites_json")
    op.drop_column("study", "created_by")
    op.drop_column("study", "organization_id")
