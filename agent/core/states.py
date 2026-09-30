"""job 상태 16개와 허용 전이표.

전이 규칙은 여기 한 곳에서만 정의하고, Store.transition()이 이 표로 검증한다.
되돌아가는 전이는 QA redo_from(reviewing → 앞 단계)과 [다시](awaiting_approval·needs_human →
storyboarding)뿐이다.
"""
from __future__ import annotations

from typing import Literal, get_args

JobState = Literal[
    "queued", "researching", "storyboarding", "producing_assets", "rendering",
    "reviewing", "packaging", "awaiting_approval", "approved", "publishing",
    "published", "measuring", "done", "rejected", "needs_human", "failed",
]
JOB_STATES: tuple[str, ...] = get_args(JobState)

# 정방향 사슬
FORWARD: tuple[str, ...] = (
    "queued", "researching", "storyboarding", "producing_assets", "rendering",
    "reviewing", "packaging", "awaiting_approval", "approved", "publishing",
    "published", "measuring", "done",
)

TERMINAL: frozenset[str] = frozenset({"done", "rejected", "failed"})

# QA가 되돌릴 수 있는 단계 (models.QAReport.redo_from 과 같다)
REDO_TARGETS: tuple[str, ...] = ("storyboarding", "producing_assets", "rendering")

# [다시] 버튼이 되돌아가는 단계
# TODO(decision): [다시]의 되돌아갈 단계 — 지금은 storyboarding(대본부터 다시).
HUMAN_REDO_TARGET = "storyboarding"

# 사람 판단을 기다리는 상태
HUMAN_WAIT: frozenset[str] = frozenset({"awaiting_approval", "needs_human"})


def _build_allowed() -> frozenset[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    for a, b in zip(FORWARD, FORWARD[1:]):
        allowed.add((a, b))
    # 실패는 끝나지 않은 모든 상태에서 가능
    for s in JOB_STATES:
        if s not in TERMINAL and s != "failed":
            allowed.add((s, "failed"))
    # QA 결과
    for target in REDO_TARGETS:
        allowed.add(("reviewing", target))
    allowed.add(("reviewing", "needs_human"))
    # 사람 판단: 승인·거절·[다시]
    for s in HUMAN_WAIT:
        allowed.add((s, "rejected"))
        allowed.add((s, HUMAN_REDO_TARGET))
    allowed.add(("needs_human", "approved"))  # [그대로 승인]
    return frozenset(allowed)


ALLOWED: frozenset[tuple[str, str]] = _build_allowed()


class InvalidTransition(ValueError):
    """전이표에 없는 전이를 시도했다."""


def is_allowed(frm: str, to: str) -> bool:
    return (frm, to) in ALLOWED


def check_transition(frm: str, to: str) -> None:
    if frm not in JOB_STATES:
        raise InvalidTransition(f"알 수 없는 상태: {frm}")
    if to not in JOB_STATES:
        raise InvalidTransition(f"알 수 없는 상태: {to}")
    if not is_allowed(frm, to):
        raise InvalidTransition(f"허용되지 않은 전이: {frm} → {to}")
