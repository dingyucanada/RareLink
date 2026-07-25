"""Initial RareLink SQLModel schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index(table: str, column: str, *, unique: bool = False) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column], unique=unique)


def upgrade() -> None:
    op.create_table(
        "study",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("research_question", sa.String(), nullable=False),
        sa.Column("disease_area", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "PROTOCOL_REVIEW",
                "FEASIBILITY_RUNNING",
                "FEASIBILITY_REVIEW",
                "CONTRACT_LOCKED",
                "TRAINING_RUNNING",
                "RESULTS_REVIEW",
                "PRIVACY_REVIEW",
                "REPORT_READY",
                "ARCHIVED",
                "BLOCKED_BY_POLICY",
                "FAILED_RETRYABLE",
                "FAILED_FINAL",
                name="studystatus",
            ),
            nullable=False,
        ),
        sa.Column("protocol_json", sa.String(), nullable=True),
        sa.Column("feasibility_json", sa.String(), nullable=True),
        sa.Column("contract_json", sa.String(), nullable=True),
        sa.Column("review_markdown", sa.String(), nullable=True),
        sa.Column("report_markdown", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("study", "title")
    _index("study", "status")

    op.create_table(
        "experiment",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("hypothesis", sa.String(), nullable=False),
        sa.Column("parameters_json", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="experimentstatus",
            ),
            nullable=False,
        ),
        sa.Column("metrics_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["study_id"], ["study.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("experiment", "study_id")
    _index("experiment", "strategy")
    _index("experiment", "status")

    op.create_table(
        "auditevent",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["study.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("auditevent", "study_id")
    _index("auditevent", "event_type")
    _index("auditevent", "created_at")

    op.create_table(
        "agentartifact",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("content_json", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["study.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("study_id", "role", "artifact_type", "source", "created_at"):
        _index("agentartifact", column)

    op.create_table(
        "trainingjob",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("experiment_id", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("backend", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="trainingjobstatus",
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("workspace", sa.String(), nullable=True),
        sa.Column("log_path", sa.String(), nullable=True),
        sa.Column("global_model_path", sa.String(), nullable=True),
        sa.Column("summary_json", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.ForeignKeyConstraint(["study_id"], ["study.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "study_id",
        "experiment_id",
        "strategy",
        "backend",
        "status",
        "created_at",
    ):
        _index("trainingjob", column)

    op.create_table(
        "physicalsite",
        sa.Column("site_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("organization", sa.String(), nullable=False),
        sa.Column("expected", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "UNKNOWN",
                "READY",
                "DEGRADED",
                "OFFLINE",
                "TRAINING",
                name="physicalsitestatus",
            ),
            nullable=False,
        ),
        sa.Column("certificate_status", sa.String(), nullable=False),
        sa.Column("data_ready", sa.Boolean(), nullable=False),
        sa.Column("gpu_ready", sa.Boolean(), nullable=False),
        sa.Column("monai_ready", sa.Boolean(), nullable=False),
        sa.Column("nvflare_ready", sa.Boolean(), nullable=False),
        sa.Column("current_job_id", sa.String(), nullable=True),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("total_rounds", sa.Integer(), nullable=False),
        sa.Column("free_memory_percent", sa.Float(), nullable=True),
        sa.Column("free_disk_percent", sa.Float(), nullable=True),
        sa.Column("dataset_fingerprint", sa.String(), nullable=True),
        sa.Column("receipt_sha256", sa.String(), nullable=True),
        sa.Column("heartbeat_json", sa.String(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("site_id"),
    )
    for column in (
        "organization",
        "expected",
        "status",
        "current_job_id",
        "dataset_fingerprint",
        "last_heartbeat_at",
    ):
        _index("physicalsite", column)

    op.create_table(
        "physicalheartbeatreceipt",
        sa.Column("heartbeat_id", sa.String(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.Column("payload_sha256", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["physicalsite.site_id"]),
        sa.PrimaryKeyConstraint("heartbeat_id"),
    )
    _index("physicalheartbeatreceipt", "site_id")
    _index("physicalheartbeatreceipt", "received_at")

    op.create_table(
        "physicalcontrolevent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("previous_hash", sa.String(), nullable=False),
        sa.Column("event_hash", sa.String(), nullable=False),
        sa.Column("algorithm", sa.String(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "event_id",
        "action",
        "actor",
        "resource_type",
        "resource_id",
        "outcome",
        "event_hash",
        "key_id",
        "created_at",
    ):
        _index("physicalcontrolevent", column, unique=column == "event_id")

    op.create_table(
        "physicalfederationjob",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=True),
        sa.Column("external_job_id", sa.String(), nullable=True),
        sa.Column("submit_token_sha256", sa.String(), nullable=True),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "APPROVAL_PENDING",
                "SUBMITTED",
                "WAITING_FOR_SITES",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "ABORTED",
                name="physicaljobstatus",
            ),
            nullable=False,
        ),
        sa.Column("bundle_sha256", sa.String(), nullable=True),
        sa.Column("contract_sha256", sa.String(), nullable=True),
        sa.Column("expected_sites_json", sa.String(), nullable=False),
        sa.Column("dataset_fingerprints_json", sa.String(), nullable=False),
        sa.Column("connected_sites_json", sa.String(), nullable=False),
        sa.Column("total_rounds", sa.Integer(), nullable=False),
        sa.Column("local_epochs", sa.Integer(), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("received_updates", sa.Integer(), nullable=False),
        sa.Column("quorum_required", sa.Integer(), nullable=False),
        sa.Column("job_directory", sa.String(), nullable=False),
        sa.Column("proposed_by", sa.String(), nullable=True),
        sa.Column("proposer_roles_json", sa.String(), nullable=False),
        sa.Column("second_approved_by", sa.String(), nullable=True),
        sa.Column("second_approval_note_sha256", sa.String(), nullable=True),
        sa.Column("second_approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approval_note", sa.String(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("previous_external_job_ids_json", sa.String(), nullable=False),
        sa.Column("global_model_path", sa.String(), nullable=True),
        sa.Column("global_model_sha256", sa.String(), nullable=True),
        sa.Column("metrics_json", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "study_id",
        "external_job_id",
        "submit_token_sha256",
        "strategy",
        "status",
        "contract_sha256",
        "proposed_by",
        "second_approved_by",
        "second_approved_at",
        "created_at",
        "updated_at",
    ):
        _index("physicalfederationjob", column)

    op.create_table(
        "physicaljobapprovalrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("contract_sha256", sa.String(), nullable=False),
        sa.Column("approver_subject_id", sa.String(), nullable=False),
        sa.Column("approver_roles_json", sa.String(), nullable=False),
        sa.Column("attestation", sa.String(), nullable=False),
        sa.Column("note_sha256", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["physicalfederationjob.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("physicaljobapprovalrecord", "job_id", unique=True)
    _index("physicaljobapprovalrecord", "contract_sha256")
    _index("physicaljobapprovalrecord", "approver_subject_id")
    _index("physicaljobapprovalrecord", "created_at")


def downgrade() -> None:
    op.drop_table("physicaljobapprovalrecord")
    op.drop_table("physicalfederationjob")
    op.drop_table("physicalcontrolevent")
    op.drop_table("physicalheartbeatreceipt")
    op.drop_table("physicalsite")
    op.drop_table("trainingjob")
    op.drop_table("agentartifact")
    op.drop_table("auditevent")
    op.drop_table("experiment")
    op.drop_table("study")

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        for enum_name in (
            "physicaljobstatus",
            "physicalsitestatus",
            "trainingjobstatus",
            "experimentstatus",
            "studystatus",
        ):
            sa.Enum(name=enum_name).drop(bind, checkfirst=True)
