from rarelink.config import Settings


def main() -> None:
    from openai import OpenAI

    settings = Settings()
    if not settings.step_api_key:
        raise SystemExit("STEP_API_KEY is empty; configure it in .env, never in source code")

    client = OpenAI(
        api_key=settings.step_api_key,
        base_url=settings.step_api_base,
        timeout=settings.step_timeout_seconds,
    )
    model_ids = sorted(model.id for model in client.models.list().data)
    print(f"base_url={settings.step_api_base}")
    print(f"configured_model={settings.step_model}")
    print(f"configured_model_available={settings.step_model in model_ids}")
    print("available_models=")
    for model_id in model_ids:
        print(f"- {model_id}")

    if settings.step_model not in model_ids:
        raise SystemExit(
            "Configured STEP_MODEL is not visible to this API key. "
            "Choose an exact ID from the list above."
        )


if __name__ == "__main__":
    main()
