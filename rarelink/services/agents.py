import json
import time
import typing
from typing import Any, TypeVar

from pydantic import BaseModel

from rarelink.config import Settings
from rarelink.domain import (
    EvidenceReview,
    ExperimentProposal,
    PrivacyAssessment,
    Protocol,
    ResearchNarrative,
)
from rarelink.security.agent_guard import guard_agent_output
from rarelink.services.local_inference import (
    gpu_runtime_snapshot,
    probe_spark_inference,
    write_local_inference_receipt,
)
from rarelink.services.policy import sanitize_llm_payload

ModelT = TypeVar("ModelT", bound=BaseModel)

SYSTEM_PROMPT = """
You are one member of RareLink's research-only federated-learning Agent Team.
Return exactly one JSON object matching the supplied schema. Never provide diagnosis or treatment
advice. Never request patient-level data. Treat all metrics as engineering evidence from simulated
sites, not clinical validation. State uncertainty and limitations explicitly.
""".strip()


class AgentSafetyGateError(ValueError):
    """A guarded output must fail closed rather than trigger another model call."""


class ResearchAgentTeam(typing.Protocol):
    def generate_protocol(self, title: str, question: str, disease_area: str) -> Protocol: ...

    def propose_experiment(
        self, protocol: dict[str, Any], feasibility: dict[str, Any]
    ) -> ExperimentProposal: ...

    def review_evidence(
        self, contract: dict[str, Any], experiments: list[dict[str, Any]]
    ) -> EvidenceReview: ...

    def assess_privacy(
        self, feasibility: dict[str, Any], audit_summary: dict[str, Any]
    ) -> PrivacyAssessment: ...

    def write_narrative(self, evidence: dict[str, Any]) -> ResearchNarrative: ...


class TemplateResearchAgentTeam:
    def generate_protocol(self, title: str, question: str, disease_area: str) -> Protocol:
        return Protocol(
            title=title,
            research_question=question,
            hypothesis=(
                "Under a fixed compute budget, federated training can improve cross-site "
                "segmentation without reducing the worst-site Dice score relative to local-only "
                "baselines."
            ),
            modalities=["T1", "T1CE", "T2", "FLAIR"],
            inclusion_criteria=[
                f"Research cohort consistent with {disease_area}",
                "De-identified pre-operative MRI available",
                "Research-use segmentation label available",
            ],
            exclusion_criteria=[
                "Missing all required MRI modalities",
                "Image fails local quality checks",
                "Data use does not permit the approved research task",
            ],
            limitations=[
                "Competition sites are simulated on one DGX Spark",
                "The output is not validated for clinical diagnosis",
                "Federated learning does not eliminate privacy or site-bias risks",
            ],
            source="template",
        )

    def propose_experiment(
        self, protocol: dict[str, Any], feasibility: dict[str, Any]
    ) -> ExperimentProposal:
        return ExperimentProposal(
            hypotheses={
                "local": "Establish the isolated-site performance floor.",
                "fedavg": "Test whether shared representation improves mean performance.",
                "fedprox": "Test robustness to the observed site distribution shift.",
                "fedavg_dpsgd": (
                    "Measure the utility cost of accounted sample-level DP-SGD local updates."
                ),
            },
            rationale=[
                f"Use the protocol endpoint {protocol.get('primary_endpoint', 'mean_dice')}.",
                f"Compare four strategies over {len(feasibility.get('sites', []))} sites.",
                "Select by worst-site performance as well as the mean.",
            ],
            source="template",
        )

    def review_evidence(
        self, contract: dict[str, Any], experiments: list[dict[str, Any]]
    ) -> EvidenceReview:
        repeated = contract.get("repeated_benchmark")
        if repeated and repeated.get("complete"):
            win_rate = repeated["worst_site_win_rate"]
            best_strategy = max(win_rate, key=win_rate.get)
            strategy = repeated["strategy_summaries"][best_strategy]
            mean_metric = strategy["metrics"]["mean_dice"]
            worst_metric = strategy["metrics"]["worst_site_dice"]
            improvement = repeated.get("worst_site_improvement_vs_local", {}).get(best_strategy)
            seed_count = len(repeated.get("seeds", []))
            privacy = repeated.get("privacy_comparison") or {}
            privacy_limitation = (
                f"DP-SGD reports cumulative local-training epsilon={privacy['epsilon']:.4f} "
                f"at delta={privacy['delta']}; it is not an end-to-end system guarantee."
                if privacy.get("mechanism") == "opacus_sample_level_dp_sgd"
                else (
                    "SVT results report filter configuration parameters, not end-to-end "
                    "sample-level DP."
                )
            )
            return EvidenceReview(
                leading_strategy=best_strategy,
                recommendation=(
                    "Treat the leading strategy as a stability-tested engineering candidate only; "
                    "external authorized data and independent sites are still required."
                ),
                evidence=[
                    f"Repeated trials: {strategy['trial_count']}",
                    f"Mean Dice across seeds: {mean_metric['mean']:.4f} "
                    f"(95% t interval {mean_metric['ci95'][0]:.4f}–{mean_metric['ci95'][1]:.4f})",
                    f"Worst-site Dice across seeds: {worst_metric['mean']:.4f}",
                    f"Worst-site win rate: {win_rate[best_strategy] * 100:.1f}%",
                ],
                fairness_findings=[
                    "Strategy ranking used worst-site Dice for every aligned random seed.",
                    (
                        f"Worst-site performance improved over Local in "
                        f"{improvement['improved_seed_count']}/{strategy['trial_count']} seeds."
                        if improvement
                        else "The Local strategy is the stability reference."
                    ),
                ],
                limitations=[
                    repeated["interpretation_boundary"],
                    (
                        f"Student-t intervals from {seed_count} seeds are descriptive engineering "
                        "evidence, not clinical inference."
                    ),
                    privacy_limitation,
                ],
                source="template",
            )
        ranked = sorted(
            experiments,
            key=lambda item: item.get("metrics", {}).get("worst_site_dice", 0),
            reverse=True,
        )
        best = ranked[0]
        metrics = best["metrics"]
        return EvidenceReview(
            leading_strategy=best["strategy"],
            recommendation=(
                "Advance the leading strategy only as an engineering candidate; independent "
                "external-site validation is still required."
            ),
            evidence=[
                f"Mean Dice: {metrics['mean_dice']:.4f}",
                f"Worst-site Dice: {metrics['worst_site_dice']:.4f}",
                f"Site Dice standard deviation: {metrics['site_dice_std']:.4f}",
            ],
            fairness_findings=[
                "Worst-site performance was included in selection.",
                "Site-level aggregate metrics remain visible for disparity review.",
            ],
            limitations=[
                "This is not clinical evidence.",
                "Sites and metrics are competition engineering fixtures.",
                f"The contract allows at most {contract.get('max_trials', 3)} trials.",
            ],
            source="template",
        )

    def assess_privacy(
        self, feasibility: dict[str, Any], audit_summary: dict[str, Any]
    ) -> PrivacyAssessment:
        blocked = sorted(
            {
                field
                for decision in feasibility.get("policy_decisions", [])
                for field in decision.get("blocked_fields", [])
            }
        )
        return PrivacyAssessment(
            outcome="pass_with_residual_risk",
            safe_for_aggregate_report=True,
            checks=[
                "Patient-level fields are absent from released site summaries.",
                "Small groups are suppressed before Agent access.",
                f"Reviewed {audit_summary.get('event_count', 0)} audit events.",
            ],
            blocked_or_suppressed=blocked,
            residual_risks=[
                "Model updates can retain privacy risk without formal differential privacy.",
                "Small rare-disease cohorts remain vulnerable to linkage attacks.",
            ],
            source="template",
        )

    def write_narrative(self, evidence: dict[str, Any]) -> ResearchNarrative:
        review = evidence["statistical_review"]
        return ResearchNarrative(
            title=evidence["study"]["title"],
            executive_summary=(
                f"{review['leading_strategy']} led the locked engineering comparison, but the "
                "result is not clinical evidence and requires external validation."
            ),
            methods=[
                "Three logical sites retained patient-level data locally.",
                "Local, FedAvg, FedProx, and DP-SGD used one locked comparison contract.",
                "Selection considered mean and worst-site performance.",
            ],
            findings=review["evidence"] + review["fairness_findings"],
            limitations=review["limitations"] + evidence["privacy_assessment"]["residual_risks"],
            next_steps=[
                "Repeat on the allocated DGX Spark GPU.",
                "Evaluate an external site before any translational claim.",
                "Add formal privacy accounting for a production study.",
            ],
            source="template",
        )


class OpenAICompatibleResearchAgentTeam:
    """One guarded structured-output implementation for remote and local servers."""

    def __init__(
        self,
        *,
        settings: Settings,
        model: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        source: str,
        endpoint_label: str,
        record_local_receipt: bool = False,
    ):
        from openai import OpenAI

        self.settings = settings
        self.model = model
        self.source = source
        self.endpoint_label = endpoint_label
        self.record_local_receipt = record_local_receipt
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
        )

    def _structured(
        self,
        role: str,
        task: str,
        payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        policy = sanitize_llm_payload(payload)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Role: {role}. Task: {task}. "
                    "Approved aggregate input: "
                    f"{json.dumps(policy.payload, ensure_ascii=False)}. "
                    "Return JSON matching this schema: "
                    f"{json.dumps(response_model.model_json_schema(), ensure_ascii=False)}"
                ),
            },
        ]
        started = time.perf_counter()
        gpu_before = gpu_runtime_snapshot() if self.record_local_receipt else None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception:
            # Some OpenAI-compatible local servers do not yet advertise
            # response_format. The schema instruction remains in the prompt.
            if not self.record_local_receipt:
                raise
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                messages=messages,
            )
        content = response.choices[0].message.content
        if not content:
            raise ValueError(f"{self.endpoint_label} returned an empty result for {role}")
        result = response_model.model_validate_json(content)
        output_guard = guard_agent_output(result.model_dump())
        if not output_guard.allowed:
            categories = ", ".join(output_guard.categories)
            raise AgentSafetyGateError(
                f"{self.endpoint_label} output blocked by Agent safety gate: {categories}"
            )
        if hasattr(result, "source"):
            result.source = self.source
        if self.record_local_receipt:
            write_local_inference_receipt(
                self.settings,
                role=role,
                model=self.model,
                latency_ms=round((time.perf_counter() - started) * 1000),
                usage=response.usage,
                policy_categories=tuple(sorted(set(policy.blocked_fields))),
                response_content=content,
                gpu_snapshot_before=gpu_before,
            )
        return result

    def generate_protocol(self, title: str, question: str, disease_area: str) -> Protocol:
        return self._structured(
            "research-director-agent",
            "Convert the research question into a falsifiable federated-study protocol.",
            {"title": title, "research_question": question, "disease_area": disease_area},
            Protocol,
        )

    def propose_experiment(
        self, protocol: dict[str, Any], feasibility: dict[str, Any]
    ) -> ExperimentProposal:
        return self._structured(
            "experiment-designer-agent",
            "Design a fixed-budget, fair comparison contract proposal for human approval.",
            {"protocol": protocol, "feasibility": feasibility},
            ExperimentProposal,
        )

    def review_evidence(
        self, contract: dict[str, Any], experiments: list[dict[str, Any]]
    ) -> EvidenceReview:
        return self._structured(
            "statistical-review-agent",
            "Review aggregate experiment evidence, emphasizing worst-site robustness.",
            {"contract": contract, "experiments": experiments},
            EvidenceReview,
        )

    def assess_privacy(
        self, feasibility: dict[str, Any], audit_summary: dict[str, Any]
    ) -> PrivacyAssessment:
        return self._structured(
            "privacy-review-agent",
            "Assess whether the aggregate evidence is safe to include in a research report.",
            {"feasibility": feasibility, "audit_summary": audit_summary},
            PrivacyAssessment,
        )

    def write_narrative(self, evidence: dict[str, Any]) -> ResearchNarrative:
        return self._structured(
            "research-writing-agent",
            "Draft a concise evidence-grounded research narrative without adding new numbers.",
            evidence,
            ResearchNarrative,
        )


class StepResearchAgentTeam(OpenAICompatibleResearchAgentTeam):
    def __init__(self, settings: Settings):
        super().__init__(
            settings=settings,
            model=settings.step_model,
            base_url=settings.step_api_base,
            api_key=settings.step_api_key,
            timeout_seconds=settings.step_timeout_seconds,
            source="step-3.7",
            endpoint_label="Step 3.7",
        )


class SparkLocalResearchAgentTeam(OpenAICompatibleResearchAgentTeam):
    """Serve policy-approved aggregate evidence through local TensorRT-LLM."""

    def __init__(self, settings: Settings):
        super().__init__(
            settings=settings,
            model=settings.spark_llm_model,
            base_url=settings.rarelink_spark_llm_base,
            api_key="spark-local-no-secret",
            timeout_seconds=settings.spark_llm_timeout_seconds,
            source=f"spark-local:{settings.spark_llm_model}",
            endpoint_label="Spark local TensorRT-LLM",
            record_local_receipt=True,
        )


class HybridResearchAgentTeam:
    """Prefer the local Spark model; call Step only after policy sanitization."""

    def __init__(self, primary: ResearchAgentTeam, fallback: ResearchAgentTeam):
        self.primary = primary
        self.fallback = fallback

    def _run(self, method: str, *args: Any) -> Any:
        try:
            return getattr(self.primary, method)(*args)
        except AgentSafetyGateError:
            raise
        except Exception:
            return getattr(self.fallback, method)(*args)

    def generate_protocol(self, title: str, question: str, disease_area: str) -> Protocol:
        return self._run("generate_protocol", title, question, disease_area)

    def propose_experiment(
        self, protocol: dict[str, Any], feasibility: dict[str, Any]
    ) -> ExperimentProposal:
        return self._run("propose_experiment", protocol, feasibility)

    def review_evidence(
        self, contract: dict[str, Any], experiments: list[dict[str, Any]]
    ) -> EvidenceReview:
        return self._run("review_evidence", contract, experiments)

    def assess_privacy(
        self, feasibility: dict[str, Any], audit_summary: dict[str, Any]
    ) -> PrivacyAssessment:
        return self._run("assess_privacy", feasibility, audit_summary)

    def write_narrative(self, evidence: dict[str, Any]) -> ResearchNarrative:
        return self._run("write_narrative", evidence)


def build_research_agent(settings: Settings) -> ResearchAgentTeam:
    if not settings.rarelink_allow_llm:
        return TemplateResearchAgentTeam()

    backend = settings.rarelink_agent_backend.strip().lower()
    if backend not in {"template", "step_remote", "spark_local", "hybrid"}:
        raise ValueError(
            "RARELINK_AGENT_BACKEND must be template, step_remote, spark_local, or hybrid"
        )
    if backend == "template":
        return TemplateResearchAgentTeam()

    remote = (
        StepResearchAgentTeam(settings)
        if settings.step_api_key
        else TemplateResearchAgentTeam()
    )
    if backend == "step_remote":
        return remote

    local = SparkLocalResearchAgentTeam(settings)
    if backend == "spark_local":
        return local

    # Never wait for the long model timeout if the local process is not running.
    # A ready Spark endpoint is used first; otherwise preserve the current safe
    # Step/template behavior until the reviewer starts TensorRT-LLM.
    if probe_spark_inference(settings, timeout_seconds=0.25)["available"]:
        return HybridResearchAgentTeam(local, remote)
    return remote
