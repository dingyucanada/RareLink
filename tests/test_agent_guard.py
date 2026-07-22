from rarelink.security.agent_guard import guard_agent_input, guard_agent_output


def test_agent_input_guard_redacts_value_secrets_and_small_groups() -> None:
    result = guard_agent_input(
        {"notes": "patient@example.org", "sample_count": 2, "mean_dice": 0.7}
    )

    assert result.allowed is True
    assert result.sanitized_payload["notes"] == "[REDACTED]"
    assert result.sanitized_payload["sample_count"] == "<5"
    assert {"email_value", "small_group"}.issubset(result.categories)


def test_agent_output_guard_blocks_clinical_and_contract_escalation() -> None:
    result = guard_agent_output(
        {"recommendation": "The diagnosis is glioma.", "raw_data_egress": True}
    )

    assert result.allowed is False
    assert set(result.categories) == {"contract_escalation", "diagnosis_or_treatment"}


def test_agent_output_guard_allows_research_only_limitation() -> None:
    result = guard_agent_output(
        {"limitation": "This is not diagnosis or treatment advice; external validation required."}
    )

    assert result.allowed is True


def test_agent_output_guard_allows_negated_clinical_validation_limitations() -> None:
    result = guard_agent_output(
        {
            "limitations": (
                "This workflow is not clinically validated and is not ready for diagnosis; "
                "external validation remains required."
            )
        }
    )

    assert result.allowed is True
