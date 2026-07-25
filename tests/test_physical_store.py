import json
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rarelink.models import PhysicalFederationJob
from rarelink.services.physical_controller import (
    PhysicalJobRecord,
    PhysicalJobState,
    ValidatedJobBundle,
)
from rarelink.services.physical_store import SqlPhysicalJobStore


def test_sql_store_round_trips_external_job_and_quorum_state(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    bundle = ValidatedJobBundle(
        directory=tmp_path / "job",
        directory_name="job",
        bundle_sha256="a" * 64,
        strategy="fedavg",
        expected_sites=("hospital-a", "hospital-b", "hospital-c"),
        total_rounds=5,
        local_epochs=1,
    )
    with Session(engine) as session:
        store = SqlPhysicalJobStore(session)
        record = PhysicalJobRecord(
            job_id="physical-job-001",
            bundle=bundle,
            state=PhysicalJobState.RUNNING,
            external_job_id="flare-job-001",
            current_round=2,
            reported_sites=("hospital-a", "hospital-b"),
            received_updates=2,
            attempt=1,
        )
        store.save(record)

        restored = store.get(record.job_id)
        model = session.get(PhysicalFederationJob, record.job_id)

        assert restored is not None
        assert restored.external_job_id == "flare-job-001"
        assert restored.reported_sites == ("hospital-a", "hospital-b")
        assert restored.bundle.bundle_sha256 == "a" * 64
        assert model is not None
        assert json.loads(model.connected_sites_json) == ["hospital-a", "hospital-b"]
        assert model.job_directory == str(tmp_path / "job")
