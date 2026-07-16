import json
import threading

from sqlmodel import Session, select

from rarelink.config import get_settings
from rarelink.database import engine
from rarelink.domain import (
    ExperimentContract,
    ExperimentStatus,
    StudyStatus,
    TrainingJobStatus,
    utc_now,
)
from rarelink.models import Experiment, Study, TrainingJob
from rarelink.services.federation import MonaiNvflareRunner
from rarelink.services.ledger import append_event
from rarelink.services.workflow import transition

SPARK_JOB_LOCK = threading.Lock()


def recover_interrupted_jobs() -> None:
    """Convert orphaned in-process jobs into explicit retryable failures after an API restart."""
    with Session(engine) as session:
        jobs = session.exec(
            select(TrainingJob).where(
                TrainingJob.status.in_([TrainingJobStatus.QUEUED, TrainingJobStatus.RUNNING])
            )
        ).all()
        for job in jobs:
            experiment = session.get(Experiment, job.experiment_id)
            study = session.get(Study, job.study_id)
            job.status = TrainingJobStatus.FAILED
            job.message = "API restarted before the in-process job completed"
            job.error = "Interrupted by API restart; the experiment can be retried safely."
            job.completed_at = utc_now()
            session.add(job)
            if experiment:
                experiment.status = ExperimentStatus.FAILED
                session.add(experiment)
            if study and study.status == StudyStatus.TRAINING_RUNNING:
                study.status = transition(study.status, StudyStatus.FAILED_RETRYABLE)
                study.updated_at = utc_now()
                append_event(
                    session,
                    study.id,
                    "training-job.interrupted",
                    "rarelink-runtime",
                    {"job_id": job.id, "experiment_id": job.experiment_id},
                )
                session.add(study)
        if jobs:
            session.commit()


def update_job_progress(job_id: str, progress: int, message: str) -> None:
    with Session(engine) as session:
        job = session.get(TrainingJob, job_id)
        if not job or job.status in {TrainingJobStatus.COMPLETED, TrainingJobStatus.FAILED}:
            return
        job.progress = max(job.progress, min(progress, 100))
        job.message = message
        session.add(job)
        session.commit()


def execute_training_job(job_id: str) -> None:
    """Execute one persisted job; the lock protects Spark unified memory from concurrent models."""
    with SPARK_JOB_LOCK:
        settings = get_settings()
        with Session(engine) as session:
            job = session.get(TrainingJob, job_id)
            if not job:
                return
            experiment = session.get(Experiment, job.experiment_id)
            study = session.get(Study, job.study_id)
            if not experiment or not study:
                return
            job.status = TrainingJobStatus.RUNNING
            job.started_at = utc_now()
            job.progress = 1
            job.message = "Acquired the DGX Spark training slot"
            append_event(
                session,
                study.id,
                "training-job.started",
                "federated-experiment-agent",
                {"job_id": job.id, "experiment_id": experiment.id, "strategy": job.strategy},
            )
            session.add(job)
            session.commit()
            contract = ExperimentContract.model_validate_json(study.contract_json or "{}")
            parameters = json.loads(experiment.parameters_json or "{}")
            strategy = job.strategy

        try:
            runner = MonaiNvflareRunner(
                settings,
                job_id,
                progress=lambda value, message: update_job_progress(job_id, value, message),
            )
            result = runner.run(strategy, parameters, contract)
            with Session(engine) as session:
                job = session.get(TrainingJob, job_id)
                experiment = session.get(Experiment, job.experiment_id) if job else None
                study = session.get(Study, job.study_id) if job else None
                if not job or not experiment or not study:
                    return
                job.status = TrainingJobStatus.COMPLETED
                job.progress = 100
                job.message = "Training evidence persisted"
                job.workspace = result.workspace
                job.log_path = result.log_path
                job.global_model_path = result.global_model_path
                job.summary_json = json.dumps(result.summary, ensure_ascii=False, default=str)
                job.completed_at = utc_now()
                experiment.metrics_json = result.metrics.model_dump_json()
                experiment.status = ExperimentStatus.COMPLETED
                experiment.completed_at = utc_now()
                session.add(job)
                session.add(experiment)
                session.flush()
                append_event(
                    session,
                    study.id,
                    "training-job.completed",
                    "federated-experiment-agent",
                    {
                        "job_id": job.id,
                        "experiment_id": experiment.id,
                        "strategy": experiment.strategy,
                        "backend": job.backend,
                        "global_model_path": job.global_model_path,
                        "metrics": result.metrics.model_dump(),
                    },
                )
                completed = set(
                    session.exec(
                        select(Experiment.strategy).where(
                            Experiment.study_id == study.id,
                            Experiment.status == ExperimentStatus.COMPLETED,
                        )
                    ).all()
                )
                if set(contract.strategies).issubset(completed):
                    study.status = transition(study.status, StudyStatus.RESULTS_REVIEW)
                    study.updated_at = utc_now()
                    session.add(study)
                session.commit()
        except Exception as exc:
            with Session(engine) as session:
                job = session.get(TrainingJob, job_id)
                experiment = session.get(Experiment, job.experiment_id) if job else None
                study = session.get(Study, job.study_id) if job else None
                if not job or not experiment or not study:
                    return
                job.status = TrainingJobStatus.FAILED
                job.message = "Training failed; inspect the persisted error and log"
                job.error = str(exc)[-8000:]
                job.completed_at = utc_now()
                experiment.status = ExperimentStatus.FAILED
                if study.status == StudyStatus.TRAINING_RUNNING:
                    study.status = transition(study.status, StudyStatus.FAILED_RETRYABLE)
                    study.updated_at = utc_now()
                append_event(
                    session,
                    study.id,
                    "training-job.failed",
                    "federated-experiment-agent",
                    {
                        "job_id": job.id,
                        "experiment_id": experiment.id,
                        "strategy": experiment.strategy,
                        "error": job.error,
                    },
                )
                session.add(job)
                session.add(experiment)
                session.add(study)
                session.commit()
