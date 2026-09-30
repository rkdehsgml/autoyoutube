"""결정론적 상태 머신.

상태 머신은 STEPS 표 하나로 정의한다. 새 단계는 행만 추가하면 된다.
produce 는 awaiting_approval 에서 멈추고, 승인은 Worker가, 게시 이후는 publish·collect가 맡는다.

안전장치
- lease(30분): 시작할 때 얻고 단계마다 연장, 끝나면 반납. 전이는 lease를 가진 실행만 가능.
- 조건부 전이: Store.transition 이 (현재 상태, lease)를 WHERE 로 확인하는 UPDATE 한 문장.
- 재시도: RetryableError·출력 검증 실패는 같은 단계를 최대 3회까지.
- QA redo_from: 최대 2회, 3번째 불합격이면 needs_human.
- 비용 상한: 역할(max_budget_usd)·job(job_budget_usd)·월(monthly_budget_usd)을 코드로 강제.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pydantic import ValidationError

from agent.core.models import Approval, PlatformMeta, QAReport, StepRun
from agent.core.ports import (
    BlobStore, BudgetExceeded, Notifier, RetryableError, StepContext, StepHandler, StepOutput, Store,
)
from agent.core.settings import RoleConfig, RuntimeSettings, load_roles
from agent.core.states import HUMAN_REDO_TARGET, HUMAN_WAIT, JobState

LEASE_TTL_SEC = 1800
MAX_ATTEMPTS = 3
MAX_QA_ROUNDS = 2
# TODO(decision): [다시] 버튼 최대 횟수 — 3회 가정. 넘으면 거절만 가능.
MAX_HUMAN_REDO = 3
RUBRIC_VERSION = "v0"


@dataclass(frozen=True)
class Step:
    to: JobState                 # 성공 시 기본 다음 상태
    handler: str                 # handlers 사전의 키
    role: str | None = None      # LLM 역할이면 이름 (역할 설정·비용 상한 적용)
    on_fail: str | None = None   # "qa_redirect"


STEPS: dict[str, Step] = {
    "queued":           Step(to="researching",       handler="start_job"),
    "researching":      Step(to="storyboarding",     handler="researcher", role="researcher"),
    "storyboarding":    Step(to="producing_assets",  handler="writer",     role="writer"),
    "producing_assets": Step(to="rendering",         handler="producer",   role="producer"),
    "rendering":        Step(to="reviewing",         handler="render_video"),              # LLM 없음
    "reviewing":        Step(to="packaging",         handler="critic",     role="critic", on_fail="qa_redirect"),
    "packaging":        Step(to="awaiting_approval", handler="publisher",  role="publisher"),  # 메타데이터 + 미리보기
}


class Orchestrator:
    def __init__(
        self,
        store: Store,
        blobs: BlobStore,
        handlers: Mapping[str, StepHandler],
        notifier: Notifier | None = None,
        roles: Mapping[str, RoleConfig] | None = None,
        lease_ttl_sec: int = LEASE_TTL_SEC,
    ):
        self.store = store
        self.blobs = blobs
        self.handlers = dict(handlers)
        self.handlers.setdefault("start_job", self._start_job)
        self.notifier = notifier
        self.roles = dict(roles) if roles is not None else load_roles()
        self.lease_ttl_sec = lease_ttl_sec
        missing = {s.handler for s in STEPS.values()} - set(self.handlers)
        if missing:
            raise ValueError(f"핸들러 없음: {sorted(missing)}")

    # ------------------------------------------------------------ 진입점
    async def advance(self, job_id: str, owner: str):
        """lease를 얻고, STEPS 표에 있는 상태인 동안 단계를 진행한다. 끝난 job을 돌려준다."""
        store = self.store
        if not store.acquire_lease(job_id, owner, self.lease_ttl_sec):
            return store.get_job(job_id)  # 다른 실행이 진행 중
        try:
            while (job := store.get_job(job_id)).state in STEPS:
                if job.state == "queued" and RuntimeSettings.from_store(store).paused:
                    break  # 일시정지 중에는 새 job을 시작하지 않는다
                if not store.acquire_lease(job_id, owner, self.lease_ttl_sec):  # 단계마다 연장
                    break
                if not await self._run_step(job, STEPS[job.state], owner):
                    break
        finally:
            store.release_lease(job_id, owner)
        return store.get_job(job_id)

    # ------------------------------------------------------------ 단계 실행
    async def _run_step(self, job, step: Step, owner: str) -> bool:
        """단계 하나를 실행하고 전이한다. 계속 진행해도 되면 True."""
        store = self.store
        settings = RuntimeSettings.from_store(store)
        if job.cost_usd >= settings.job_budget_usd:
            return self._fail(job, owner, f"job 비용 상한 초과: ${job.cost_usd:.2f} ≥ ${settings.job_budget_usd:.2f}")

        role_cfg = self.roles.get(step.role) if step.role else None
        run_id = store.record_step(StepRun(job_id=job.id, step=job.state, role=step.role, status="started",
                                           gh_run_id=owner))
        ctx = StepContext(job=job, store=store, blobs=self.blobs, step=job.state, role=step.role,
                          role_config=role_cfg, notifier=self.notifier)
        try:
            out = await self.handlers[step.handler](ctx)
            if not isinstance(out, StepOutput):
                raise TypeError(f"{step.handler} 이(가) StepOutput 을 돌려주지 않았습니다")
        except (RetryableError, ValidationError) as e:
            self._end_step(run_id, job, step, "failed", error=_short(e))
            if job.attempt + 1 >= MAX_ATTEMPTS:
                return self._fail(job, owner, f"{MAX_ATTEMPTS}회 재시도 실패: {_short(e)}")
            store.bump_attempt(job.id)
            return True  # 같은 단계를 다시
        except BudgetExceeded as e:
            self._end_step(run_id, job, step, "failed", error=_short(e))
            return self._fail(job, owner, _short(e))
        except Exception as e:  # 예상 못 한 오류는 재시도하지 않는다
            self._end_step(run_id, job, step, "failed", error=_short(e))
            return self._fail(job, owner, f"{type(e).__name__}: {_short(e)}")

        # 비용은 쓴 만큼 먼저 기록하고 상한을 확인한다
        if out.cost_usd:
            store.record_run(job.id, step.role or step.handler, out.cost_usd, out.usage)
        self._end_step(run_id, job, step, "ok", out=out)
        if role_cfg and out.cost_usd > role_cfg.max_budget_usd:
            return self._fail(job, owner, f"{step.role} 역할 비용 상한 초과: ${out.cost_usd:.2f} > "
                                          f"${role_cfg.max_budget_usd:.2f}")
        spent = job.cost_usd + out.cost_usd
        if spent > settings.job_budget_usd:
            return self._fail(job, owner, f"job 비용 상한 초과: ${spent:.2f} > ${settings.job_budget_usd:.2f}")

        fields = dict(out.job_fields)
        fields["attempt"] = 0
        next_state = out.next_state or step.to
        if step.on_fail == "qa_redirect":
            if not isinstance(out.output, QAReport):
                return self._fail(job, owner, "critic 이 QAReport 를 돌려주지 않았습니다")
            next_state, extra = self._qa_redirect(job, out.output)
            fields.update(extra)

        if not store.transition(job.id, job.state, next_state, owner=owner, **fields):
            store.add_event("transition_lost", json.dumps({"job_id": job.id, "from": job.state, "to": next_state}))
            return False  # lease를 잃었거나 다른 실행이 상태를 바꿨다

        if next_state == "needs_human":
            self._send(f"사람 확인 필요: {job.id} — QA {job.qa_rounds}회 재작업 후에도 불합격")
            return False
        if next_state == "awaiting_approval":
            self._send_preview(job.id)
        return True

    def _qa_redirect(self, job, report: QAReport) -> tuple[str, dict]:
        store = self.store
        store.add_evals(job.id, RUBRIC_VERSION, report.scores, "llm")
        if report.passed:
            return "packaging", {}
        reason = "; ".join(report.fixes) or None
        if report.redo_from is None:
            store.add_decision(job.id, "critic", "needs_human", reason)
            return "needs_human", {}
        if job.qa_rounds >= MAX_QA_ROUNDS:
            store.add_decision(job.id, "critic", f"needs_human (redo {job.qa_rounds}회 초과)", reason)
            return "needs_human", {}
        store.add_decision(job.id, "critic", f"redo_from={report.redo_from}", reason)
        return report.redo_from, {"qa_rounds": job.qa_rounds + 1}

    # ------------------------------------------------------------ 기본 핸들러
    async def _start_job(self, ctx: StepContext) -> StepOutput:
        settings = RuntimeSettings.from_store(ctx.store)
        month = ctx.store.month_cost()
        if month >= settings.monthly_budget_usd:
            raise BudgetExceeded(f"월 비용 상한 초과: ${month:.2f} ≥ ${settings.monthly_budget_usd:.2f}")
        fields = {}
        sha = os.environ.get("GITHUB_SHA")
        if sha:
            fields["config_version"] = sha
        return StepOutput(job_fields=fields)

    # ------------------------------------------------------------ 보조
    def _end_step(self, run_id: int, job, step: Step, status: str, out: StepOutput | None = None,
                  error: str | None = None) -> None:
        usage = out.usage if out else {}
        self.store.record_step(StepRun(
            id=run_id, job_id=job.id, step=job.state, role=step.role, status=status,
            cost_usd=out.cost_usd if out else 0.0,
            tokens_in=usage.get("tokens_in"), tokens_out=usage.get("tokens_out"), error=error,
        ))

    def _fail(self, job, owner: str, error: str) -> bool:
        if self.store.transition(job.id, job.state, "failed", owner=owner, error=error[:500]):
            self.store.add_event("job_failed", json.dumps({"job_id": job.id, "state": job.state, "error": error},
                                                          ensure_ascii=False))
            self._send(f"실패: {job.id} ({job.state}) {error}")
        return False

    def _send(self, text: str) -> None:
        if self.notifier:
            self.notifier.send(text)

    def _send_preview(self, job_id: str) -> None:
        if not self.notifier:
            return
        job = self.store.get_job(job_id)
        finals = self.store.artifacts(job_id, "final")
        metas = self.store.artifacts(job_id, "meta")
        if not finals or not metas:
            return
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = self.blobs.get(metas[0].r2_key, Path(tmp) / "meta.json")
            meta = PlatformMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            video = self.blobs.get(finals[0].r2_key, Path(tmp) / "final.mp4")
            self.notifier.preview(job, video, meta)


def apply_decision(store: Store, job_id: str, decision: str, reason: str | None = None):
    """사람의 판단(승인·거절·[다시])을 기록하고 전이한다.

    클라우드에서는 Worker가 approvals 를 기록하고 같은 전이를 한다(4·5단계). 로컬에서는 CLI가 대신한다.
    """
    job = store.get_job(job_id)
    if job.state not in HUMAN_WAIT:
        raise ValueError(f"사람 판단을 기다리는 상태가 아닙니다: {job.state}")
    fields: dict = {}
    if decision == "approved":
        to = "approved"
    elif decision == "rejected":
        to = "rejected"
    elif decision == "redo":
        done = store.query(
            "SELECT COUNT(*) AS n FROM decisions WHERE job_id = ? AND role = 'human' AND action = 'redo'", [job_id]
        )[0]["n"]
        if done >= MAX_HUMAN_REDO:
            raise ValueError(f"[다시]는 최대 {MAX_HUMAN_REDO}회입니다")
        to = HUMAN_REDO_TARGET
        # TODO(decision): [다시] 후 QA 재작업 횟수를 새로 셀지 — 지금은 0으로 초기화.
        fields = {"qa_rounds": 0, "attempt": 0, "error": None}
    else:
        raise ValueError(f"알 수 없는 판단: {decision}")
    if not store.transition(job_id, job.state, to, **fields):
        raise RuntimeError("상태가 바뀌어 판단을 적용하지 못했습니다")
    store.put_approval(Approval(job_id=job_id, decision=decision, reason=reason))
    store.add_decision(job_id, "human", decision, reason)
    return store.get_job(job_id)


def _short(e: BaseException, limit: int = 300) -> str:
    text = str(e).replace("\n", " ")
    return text[:limit]
