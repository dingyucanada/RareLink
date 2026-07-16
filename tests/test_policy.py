from rarelink.services.policy import sanitize_llm_payload, sanitize_site_aggregate


def test_site_policy_suppresses_small_groups_and_identifiers() -> None:
    decision = sanitize_site_aggregate(
        {
            "site_id": "site-a",
            "sample_count": 12,
            "age_buckets": {"0-5": 2, "6-12": 10},
            "patient_id_list": ["never-release"],
        },
        min_group_size=5,
    )

    assert decision.payload["age_buckets"]["0-5"] == "<5"
    assert "patient_id_list" not in decision.payload
    assert "patient_id_list" in decision.blocked_fields
    assert "age_buckets.0-5" in decision.blocked_fields


def test_llm_policy_removes_nested_patient_fields() -> None:
    decision = sanitize_llm_payload(
        {"research_question": "aggregate question", "context": {"patient_name": "blocked"}}
    )

    assert decision.payload == {"research_question": "aggregate question", "context": {}}
    assert decision.result == "released_with_redaction"
