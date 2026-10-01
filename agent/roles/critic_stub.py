"""3단계 critic 전 임시 심사 — live 실행에서 항상 통과시키고 점수는 남기지 않는다."""
from __future__ import annotations

from agent.core.models import QAReport
from agent.core.ports import StepContext, StepOutput
from agent.roles.deps import RoleDeps, put_json


async def run(ctx: StepContext, deps: RoleDeps) -> StepOutput:
    # TODO(decision): 3단계 전 live 실행의 QA — 지금은 무조건 통과 (사람 승인 단계에서 확인).
    report = QAReport(scores={}, passed=True, redo_from=None, fixes=[])
    put_json(ctx, "qa/report.json", report, "qa", provider="passthrough")
    return StepOutput(output=report)
