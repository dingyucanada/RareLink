import json
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
from rarelink.services.policy import sanitize_llm_payload

ModelT = TypeVar("ModelT", bound=BaseModel)

SYSTEM_PROMPT = """
You are one member of RareLink's research-only federated-learning Agent Team.
Return exactly one JSON object matching the supplied schema. Never provide diagnosis or treatment
advice. Never request patient-level data. Treat all metrics as engineering evidence from simulated
sites, not clinical validation. State uncertainty and limitations explicitly.
""".strip()


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
            },
            rationale=[
                f"Use the protocol endpoint {protocol.get('primary_endpoint', 'mean_dice')}.",
                f"Compare three strategies over {len(feasibility.get('sites', []))} sites.",
                "Select by worst-site performance as well as the mean.",
            ],
            source="template",
        )

    def review_evidence(
        self, contract: dict[str, Any], experiments: list[dict[str, Any]]
    ) -> EvidenceReview:
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
                "Local, FedAvg, and FedProx used the same locked comparison contract.",
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


class StepResearchAgentTeam:
    def __init__(self, settings: Settings):
        from openai import OpenAI

        self.model = settings.step_model
        self.client = OpenAI(
            api_key=settings.step_api_key,
            base_url=settings.step_api_base,
            timeout=settings.step_timeout_seconds,
        )

    def _structured(
        self,
        role: str,
        task: str,
        payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        policy = sanitize_llm_payload(payload)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
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
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError(f"Step 3.7 returned an empty result for {role}")
        result = response_model.model_validate_json(content)
        if hasattr(result, "source"):
            result.source = "step-3.7"
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


def build_research_agent(settings: Settings) -> ResearchAgentTeam:
    if settings.rarelink_allow_llm and settings.step_api_key:
        return StepResearchAgentTeam(settings)
    return TemplateResearchAgentTeam()
