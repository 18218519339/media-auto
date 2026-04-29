from __future__ import annotations


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "created": {"reading", "failed", "canceled"},
    "reading": {"rewriting", "failed", "canceled"},
    "rewriting": {"image_generating", "awaiting_review", "failed", "canceled"},
    "image_generating": {"awaiting_review", "failed", "canceled"},
    "awaiting_review": {"approved", "failed", "canceled"},
    "approved": {"wechat_draft_saving", "scheduled", "failed", "canceled"},
    "wechat_draft_saving": {"wechat_draft_saved", "failed", "canceled"},
    "wechat_draft_saved": {"scheduled", "failed", "canceled"},
    "scheduled": {"publishing", "failed", "canceled"},
    "publishing": {"succeeded", "failed", "canceled"},
    "succeeded": set(),
    "failed": {"reading", "rewriting", "image_generating", "scheduled", "canceled"},
    "canceled": set(),
}


class InvalidTransitionError(ValueError):
    pass


def ensure_transition(current: str, target: str) -> None:
    if current == target:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(f"Cannot transition from {current} to {target}")
