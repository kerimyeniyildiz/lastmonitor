from __future__ import annotations

from collections.abc import Iterator


ATTENTION_ERROR_NAMES = {
    "BadPassword",
    "ChallengeRequired",
    "FeedbackRequired",
    "LoginRequired",
    "PleaseWaitFewMinutes",
    "TwoFactorRequired",
}

ATTENTION_MARKERS = (
    "bad_password",
    "challenge_required",
    "feedback_required",
    "login_required",
    "please_wait_a_few_minutes",
    "two_factor_required",
)


def iter_exception_chain(error: BaseException) -> Iterator[BaseException]:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def requires_manual_attention(error: BaseException) -> bool:
    for current in iter_exception_chain(error):
        if type(current).__name__ in ATTENTION_ERROR_NAMES:
            return True
        message = str(current).strip().lower().replace(" ", "_")
        if any(marker in message for marker in ATTENTION_MARKERS):
            return True
    return False


def is_login_required(error: BaseException) -> bool:
    for current in iter_exception_chain(error):
        if type(current).__name__ == "LoginRequired":
            return True
        if "login_required" in str(current).strip().lower().replace(" ", "_"):
            return True
    return False
