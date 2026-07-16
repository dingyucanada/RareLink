import json

from rarelink.config import Settings
from rarelink.services.agents import build_research_agent


def main() -> None:
    settings = Settings()
    if not settings.step_api_key:
        raise SystemExit("STEP_API_KEY is empty; configure it in .env")

    protocol = build_research_agent(settings).generate_protocol(
        title="RareLink synthetic federated study",
        question=(
            "Can federated learning improve worst-site segmentation robustness on a fully "
            "synthetic three-site cohort?"
        ),
        disease_area="synthetic rare-disease imaging benchmark",
    )
    print(
        json.dumps(
            {
                "source": protocol.source,
                "title": protocol.title,
                "modalities": protocol.modalities,
                "primary_endpoint": protocol.primary_endpoint,
                "guardrail_metrics": protocol.guardrail_metrics,
                "limitation_count": len(protocol.limitations),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
