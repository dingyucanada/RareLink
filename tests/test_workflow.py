import pytest

from rarelink.domain import StudyStatus
from rarelink.services.workflow import InvalidTransition, transition


def test_valid_transition() -> None:
    assert transition(StudyStatus.DRAFT, StudyStatus.PROTOCOL_REVIEW) == StudyStatus.PROTOCOL_REVIEW


def test_contract_cannot_skip_feasibility() -> None:
    with pytest.raises(InvalidTransition):
        transition(StudyStatus.PROTOCOL_REVIEW, StudyStatus.CONTRACT_LOCKED)
