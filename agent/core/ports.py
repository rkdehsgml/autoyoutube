"""바깥 세계와의 경계 (Protocol).

D1·R2·TTS·생성 모델·플랫폼·텔레그램은 전부 이 Protocol 뒤에 숨는다.
클라우드·로컬·테스트는 구현체만 바꾸고 상태 머신과 역할 코드는 그대로다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from agent.core.models import (
    Approval,
    Artifact,
    Job,
    MediaRef,
    MetricRow,
    PlatformMeta,
    Publication,
    SceneAudio,
    StepRun,
    Storyboard,
    Topic,
    VisualResult,
    VisualSpec,
)
from agent.core.states import JobState


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class Store(Protocol):  # D1HttpStore(4단계) | SqliteStore
    # jobs
    def create_job(self, origin: str, requested_topic: str | None = None, format_id: str | None = None,
                   job_id: str | None = None, config_version: str | None = None) -> Job: ...
    def get_job(self, job_id: str) -> Job: ...
    def list_jobs(self, state: str | None = None, limit: int = 20) -> list[Job]: ...
    def acquire_lease(self, job_id: str, owner: str, ttl_sec: int) -> bool: ...
    def release_lease(self, job_id: str, owner: str) -> None: ...
    def transition(self, job_id: str, frm: JobState, to: JobState, *, owner: str | None = None,
                   **fields: Any) -> bool: ...  # 단일 조건부 UPDATE
    def bump_attempt(self, job_id: str) -> None: ...
    # 기록
    def record_step(self, run: StepRun) -> int: ...
    def step_runs(self, job_id: str) -> list[StepRun]: ...
    def record_run(self, job_id: str, role: str, cost_usd: float, usage: dict) -> None: ...
    def put_artifact(self, a: Artifact) -> None: ...
    def artifacts(self, job_id: str, kind: str | None = None) -> list[Artifact]: ...
    def add_evals(self, job_id: str, rubric_version: str, scores: dict[str, float], judge: str) -> None: ...
    def add_topic(self, t: Topic) -> Topic: ...
    def add_decision(self, job_id: str | None, role: str, action: str, reason: str | None = None) -> None: ...
    def add_event(self, kind: str, payload: str | None = None) -> None: ...
    # 승인·게시 (approvals 는 클라우드에서 Worker만 기록)
    def put_approval(self, a: Approval) -> None: ...
    def approval(self, job_id: str) -> Approval | None: ...
    def upsert_publication(self, p: Publication) -> None: ...
    # 설정·비용
    def get_setting(self, key: str, default: str | None = None) -> str | None: ...
    def set_setting(self, key: str, value: str) -> None: ...
    def month_cost(self) -> float: ...
    def query(self, sql: str, params: list | None = None) -> list[dict]: ...  # 분석용 읽기 전용


@runtime_checkable
class BlobStore(Protocol):  # R2Store(4단계) | LocalBlobStore
    def put(self, key: str, src: Path | bytes, content_type: str) -> str: ...
    def get(self, key: str, dest: Path) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def presigned_get(self, key: str, expires: int = 3600) -> str: ...


class TTSProvider(Protocol):  # EdgeTTS | GoogleChirp | MockTTS (2단계)
    def synthesize(self, text: str, voice: str, out: Path) -> SceneAudio: ...


class VisualProvider(Protocol):  # PexelsStock | NanoBananaImage | VeoVideo | Placeholder (2·7단계)
    kind: Literal["stock", "image", "video"]

    def create(self, spec: VisualSpec, out: Path) -> VisualResult: ...  # cost_usd 포함


class Judge(Protocol):  # GeminiVideoJudge | RuleChecks (3단계)
    def score(self, video: Path, storyboard: Storyboard) -> dict[str, float]: ...


class Publisher(Protocol):  # YouTubePublisher | InstagramPublisher | NaverKitPublisher (5단계)
    platform: str

    def publish(self, job: Job, media: MediaRef, meta: PlatformMeta) -> str: ...  # post_id
    def metrics(self, post_id: str, span: Literal["48h", "7d"]) -> MetricRow: ...


@runtime_checkable
class Notifier(Protocol):  # TelegramNotifier | MemoryNotifier
    def preview(self, job: Job, video: Path, meta: PlatformMeta) -> str: ...  # message_id
    def send(self, text: str) -> None: ...


# ---------------------------------------------------------------- 역할 실행 계약


@dataclass
class StepContext:
    """단계 하나를 실행할 때 역할·결정론 단계가 받는 입력."""

    job: Job
    store: Store
    blobs: BlobStore
    step: str
    role: str | None = None
    role_config: Any = None  # agent.core.settings.RoleConfig
    notifier: Notifier | None = None


@dataclass
class StepOutput:
    """단계 실행 결과. 오케스트레이터가 비용·산출물·전이를 기록한다."""

    output: BaseModel | None = None
    next_state: JobState | None = None       # None 이면 STEPS 표의 기본 다음 상태
    cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)  # tokens_in, tokens_out
    job_fields: dict = field(default_factory=dict)  # topic_id, format_id 등


class StepHandler(Protocol):
    async def __call__(self, ctx: StepContext) -> StepOutput: ...


class RetryableError(RuntimeError):
    """일시 오류 — 같은 단계를 다시 시도한다 (최대 3회)."""


class BudgetExceeded(RuntimeError):
    """역할·job·월 비용 상한 초과."""
