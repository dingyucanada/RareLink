import json
import math
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from rarelink.config import Settings
from rarelink.domain import ExperimentContract, ExperimentMetrics, SiteMetrics


class FederationRunner(Protocol):
    def run(
        self,
        strategy: str,
        parameters: dict[str, object],
        contract: ExperimentContract,
    ) -> ExperimentMetrics: ...


@dataclass
class FederationRunResult:
    metrics: ExperimentMetrics
    workspace: str
    log_path: str | None
    global_model_path: str | None
    summary: dict[str, Any]


class MockFederationRunner:
    """Deterministic runner for UI/API development; never presented as a GPU experiment."""

    BASELINES = {
        "local": [0.61, 0.55, 0.49],
        "fedavg": [0.72, 0.66, 0.58],
        "fedprox": [0.73, 0.68, 0.63],
        "fedavg_dpsgd": [0.69, 0.63, 0.56],
    }

    def run(
        self,
        strategy: str,
        parameters: dict[str, object],
        contract: ExperimentContract,
    ) -> ExperimentMetrics:
        normalized = strategy.lower()
        if normalized not in contract.strategies:
            raise ValueError(f"Strategy {normalized!r} is outside the locked experiment contract")
        if normalized not in self.BASELINES:
            raise ValueError(f"Mock runner does not support strategy {normalized!r}")

        rng = random.Random(f"{contract.split_seed}:{normalized}:{sorted(parameters.items())}")
        dice_values = [
            round(base + rng.uniform(-0.006, 0.006), 4) for base in self.BASELINES[normalized]
        ]
        hd95_values = [
            round(20.0 - dice * 13.0 + rng.uniform(-0.4, 0.4), 3) for dice in dice_values
        ]
        mean = sum(dice_values) / len(dice_values)
        variance = sum((value - mean) ** 2 for value in dice_values) / len(dice_values)
        sites = [
            SiteMetrics(site_id=site, dice=dice, hd95=hd95)
            for site, dice, hd95 in zip(contract.sites, dice_values, hd95_values, strict=True)
        ]
        return ExperimentMetrics(
            mean_dice=round(mean, 4),
            worst_site_dice=min(dice_values),
            site_dice_std=round(math.sqrt(variance), 4),
            hd95=round(sum(hd95_values) / len(hd95_values), 3),
            sites=sites,
        )


class MonaiNvflareRunner:
    """Run the existing MONAI/NVFLARE entry points in an isolated job workspace."""

    def __init__(
        self,
        settings: Settings,
        job_id: str,
        progress: Callable[[int, str], None] | None = None,
    ):
        self.settings = settings
        self.job_id = job_id
        self.progress = progress or (lambda _value, _message: None)
        self.workspace = (settings.artifact_root / "training-jobs" / job_id).resolve()
        self.manifest: Path | None = None

    def run(
        self,
        strategy: str,
        parameters: dict[str, object],
        contract: ExperimentContract,
    ) -> FederationRunResult:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.manifest = (
            self.settings.data_root / contract.dataset_version / "manifest.json"
        ).resolve()
        if not self.manifest.exists():
            raise FileNotFoundError(
                f"Dataset manifest is missing: {self.manifest}. Generate synthetic data first."
            )
        normalized = strategy.lower()
        if normalized == "local":
            return self._run_local(contract)
        if normalized in {"fedavg", "fedprox", "fedavg_dpsgd"}:
            return self._run_nvflare(normalized, parameters, contract)
        raise ValueError(f"Real runner does not support strategy {normalized!r}")

    def _run_local(self, contract: ExperimentContract) -> FederationRunResult:
        from rarelink.imaging.monai_runner import run_monai_smoke

        output = self.workspace / "local-models"
        site_metrics: list[SiteMetrics] = []
        raw_results: list[dict[str, Any]] = []
        for index, site in enumerate(contract.sites, start=1):
            self.progress(
                5 + int((index - 1) / len(contract.sites) * 85),
                f"Training isolated baseline at {site}",
            )
            result = run_monai_smoke(
                self.manifest,
                site,
                output,
                epochs=contract.local_epochs,
                seed=contract.split_seed + index,
            )
            raw_results.append(result)
            site_metrics.append(
                SiteMetrics(
                    site_id=site,
                    dice=result["mean_foreground_dice"],
                    hd95=result.get("hd95"),
                )
            )
        metrics = self._aggregate(site_metrics)
        summary = {
            "strategy": "local",
            "manifest": str(self.manifest),
            "workspace": str(self.workspace),
            "metrics": metrics.model_dump(),
            "site_results": raw_results,
            "simulated_sites": True,
        }
        summary_path = self.workspace / "local-summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        self.progress(100, "Three isolated-site baselines completed")
        return FederationRunResult(
            metrics=metrics,
            workspace=str(self.workspace),
            log_path=None,
            global_model_path=None,
            summary=summary,
        )

    def _run_nvflare(
        self,
        strategy: str,
        parameters: dict[str, object],
        contract: ExperimentContract,
    ) -> FederationRunResult:
        project_root = Path(__file__).resolve().parents[2]
        script = project_root / "scripts" / "run_nvflare_simulation.py"
        metrics_dir = self.workspace / "site-metrics"
        log_path = self.workspace / f"{strategy}.log"
        command = [
            sys.executable,
            str(script),
            "--manifest",
            str(self.manifest),
            "--strategy",
            strategy,
            "--rounds",
            str(contract.rounds),
            "--local-epochs",
            str(contract.local_epochs),
            "--workspace",
            str(self.workspace),
            "--metrics-dir",
            str(metrics_dir),
        ]
        if strategy == "fedprox":
            command.extend(["--fedprox-mu", str(parameters.get("mu", 0.01))])
        if strategy == "fedavg_dpsgd":
            command.extend(
                [
                    "--dp-noise-multiplier",
                    str(parameters.get("noise_multiplier", 1.2)),
                    "--dp-max-grad-norm",
                    str(parameters.get("max_grad_norm", 1.0)),
                    "--dp-delta",
                    str(parameters.get("delta", 1e-5)),
                ]
            )

        self.progress(5, f"Starting NVIDIA FLARE {strategy.upper()} recipe")
        with log_path.open("w", encoding="utf-8") as log_stream:
            process = subprocess.Popen(
                command,
                cwd=project_root,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
            )
            while process.poll() is None:
                completed_updates = len(list(metrics_dir.glob("site-*-round-*.json")))
                expected_updates = max(1, len(contract.sites) * contract.rounds)
                progress = min(90, 10 + int(completed_updates / expected_updates * 80))
                self.progress(
                    progress,
                    f"Received {completed_updates}/{expected_updates} site-round updates",
                )
                time.sleep(1)
        if process.returncode != 0:
            details = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"NVIDIA FLARE job failed. Log tail: {details}")

        summary_path = self.workspace / f"{strategy}-summary.json"
        if not summary_path.exists():
            raise RuntimeError(f"NVIDIA FLARE summary is missing: {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not summary.get("metrics") or len(summary["metrics"].get("sites", [])) != len(
            contract.sites
        ):
            raise RuntimeError("NVIDIA FLARE finished without complete aggregate site metrics")
        metrics = ExperimentMetrics.model_validate(summary["metrics"])
        self.progress(100, f"{strategy.upper()} global model and aggregate metrics persisted")
        return FederationRunResult(
            metrics=metrics,
            workspace=str(self.workspace),
            log_path=str(log_path),
            global_model_path=summary.get("global_model"),
            summary=summary,
        )

    @staticmethod
    def _aggregate(sites: list[SiteMetrics]) -> ExperimentMetrics:
        dice_values = [item.dice for item in sites]
        hd95_values = [item.hd95 for item in sites if item.hd95 is not None]
        return ExperimentMetrics(
            mean_dice=round(statistics.fmean(dice_values), 6),
            worst_site_dice=min(dice_values),
            site_dice_std=round(statistics.pstdev(dice_values), 6),
            hd95=round(statistics.fmean(hd95_values), 6) if hd95_values else None,
            sites=sites,
        )


def build_federation_runner(mode: str) -> FederationRunner:
    if mode == "mock":
        return MockFederationRunner()
    raise RuntimeError(
        f"Federation mode {mode!r} is not installed yet. Use mock locally; Spark mode requires "
        "the validated NVIDIA FLARE adapter."
    )
