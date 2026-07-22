import json

from rarelink.config import Settings
from rarelink.services.agents import StepResearchAgentTeam


def main() -> None:
    settings = Settings()
    if not settings.step_api_key:
        raise SystemExit("STEP_API_KEY is empty; configure it in .env")
    # Explicit remote integration test: a local endpoint must never make a
    # Step verification look passed through hybrid fallback behavior.
    team = StepResearchAgentTeam(settings)

    protocol = {
        "title": "RareLink synthetic federated study",
        "research_question": "Can federated learning improve worst-site robustness?",
        "primary_endpoint": "mean_dice",
        "guardrail_metrics": ["worst_site_dice", "site_dice_std", "hd95"],
        "allowed_strategies": ["local", "fedavg", "fedprox"],
        "limitations": ["Synthetic engineering evidence only"],
    }
    feasibility = {
        "mode": "simulated_sites",
        "sites": [
            {"site_id": "site-a", "usable_count": 30, "missing_modality_rate": 0.08},
            {"site_id": "site-b", "usable_count": 25, "missing_modality_rate": 0.11},
            {"site_id": "site-c", "usable_count": 14, "missing_modality_rate": 0.18},
        ],
        "policy_decisions": [
            {
                "result": "released_with_suppression",
                "blocked_fields": ["age_buckets.0-5", "patient_id_list"],
            }
        ],
    }
    proposal = team.propose_experiment(protocol, feasibility)
    contract = proposal.model_dump(exclude={"hypotheses", "rationale", "source"})
    contract["max_trials"] = proposal.max_trials
    experiments = [
        {
            "strategy": "local",
            "metrics": {
                "mean_dice": 0.55,
                "worst_site_dice": 0.49,
                "site_dice_std": 0.05,
                "hd95": 12.8,
            },
        },
        {
            "strategy": "fedavg",
            "metrics": {
                "mean_dice": 0.66,
                "worst_site_dice": 0.58,
                "site_dice_std": 0.06,
                "hd95": 11.4,
            },
        },
        {
            "strategy": "fedprox",
            "metrics": {
                "mean_dice": 0.68,
                "worst_site_dice": 0.63,
                "site_dice_std": 0.04,
                "hd95": 10.9,
            },
        },
    ]
    review = team.review_evidence(contract, experiments)
    privacy = team.assess_privacy(
        feasibility,
        {
            "event_count": 14,
            "event_types": ["protocol.generated", "experiment.completed"],
            "contains_patient_level_data": False,
        },
    )
    narrative = team.write_narrative(
        {
            "study": {
                "title": protocol["title"],
                "research_question": protocol["research_question"],
            },
            "protocol": protocol,
            "contract": contract,
            "experiments": experiments,
            "statistical_review": review.model_dump(),
            "privacy_assessment": privacy.model_dump(),
        }
    )
    sources = [proposal.source, review.source, privacy.source, narrative.source]
    if any(source != "step-3.7" for source in sources):
        raise RuntimeError(f"Expected four Step 3.7 artifacts, received {sources!r}")
    print(
        json.dumps(
            {
                "experiment_designer": {
                    "source": proposal.source,
                    "strategies": proposal.strategies,
                    "rounds": proposal.rounds,
                },
                "statistical_reviewer": {
                    "source": review.source,
                    "leading_strategy": review.leading_strategy,
                    "evidence_count": len(review.evidence),
                },
                "privacy_reviewer": {
                    "source": privacy.source,
                    "outcome": privacy.outcome,
                    "safe_for_aggregate_report": privacy.safe_for_aggregate_report,
                },
                "research_writer": {
                    "source": narrative.source,
                    "title": narrative.title,
                    "limitation_count": len(narrative.limitations),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
