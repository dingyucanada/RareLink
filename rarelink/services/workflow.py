from rarelink.domain import StudyStatus


class InvalidTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[StudyStatus, set[StudyStatus]] = {
    StudyStatus.DRAFT: {StudyStatus.PROTOCOL_REVIEW},
    StudyStatus.PROTOCOL_REVIEW: {StudyStatus.FEASIBILITY_RUNNING},
    StudyStatus.FEASIBILITY_RUNNING: {
        StudyStatus.FEASIBILITY_REVIEW,
        StudyStatus.BLOCKED_BY_POLICY,
        StudyStatus.FAILED_RETRYABLE,
    },
    StudyStatus.FEASIBILITY_REVIEW: {StudyStatus.CONTRACT_LOCKED},
    StudyStatus.CONTRACT_LOCKED: {StudyStatus.TRAINING_RUNNING},
    StudyStatus.TRAINING_RUNNING: {
        StudyStatus.RESULTS_REVIEW,
        StudyStatus.FAILED_RETRYABLE,
        StudyStatus.FAILED_FINAL,
    },
    StudyStatus.RESULTS_REVIEW: {StudyStatus.PRIVACY_REVIEW},
    StudyStatus.PRIVACY_REVIEW: {
        StudyStatus.REPORT_READY,
        StudyStatus.BLOCKED_BY_POLICY,
    },
    StudyStatus.REPORT_READY: {StudyStatus.ARCHIVED},
    StudyStatus.FAILED_RETRYABLE: {
        StudyStatus.FEASIBILITY_RUNNING,
        StudyStatus.TRAINING_RUNNING,
    },
}


def transition(current: StudyStatus, target: StudyStatus) -> StudyStatus:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"Cannot transition study from {current} to {target}")
    return target
