"""Pydantic 모델.

- 행 모델: worker/migrations/0001_init.sql 의 12개 테이블과 1:1.
- 역할 입출력 모델: 역할의 출력은 model_json_schema()를 그대로 output_format에 넣고,
  받은 JSON은 여기서 검증한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.core.states import JobState

# ---------------------------------------------------------------- 행 모델 (테이블 1:1)


class Row(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Setting(Row):
    key: str
    value: str


class Topic(Row):
    id: str
    title: str
    norm_hash: str
    source: Literal["youtube", "naver", "web", "manual"]
    angle: str | None = None
    evidence_url: str | None = None
    score: float = 0.0
    status: Literal["new", "used", "rejected"] = "new"
    created_at: str | None = None


class Job(Row):
    id: str
    origin: Literal["cron", "telegram", "manual", "redo"]
    topic_id: str | None = None
    requested_topic: str | None = None
    format_id: str | None = None
    config_version: str | None = None
    state: JobState = "queued"
    attempt: int = 0
    qa_rounds: int = 0
    lease_owner: str | None = None
    lease_until: str | None = None
    cost_usd: float = 0.0
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class StepRun(Row):
    id: int | None = None
    job_id: str
    step: str
    role: str | None = None
    status: Literal["started", "ok", "failed"]
    input_hash: str | None = None
    cost_usd: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    gh_run_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None


ArtifactKind = Literal["research", "storyboard", "audio", "visual", "subs", "final", "thumb", "qa", "meta",
                       "manifest"]


class Artifact(Row):
    job_id: str
    kind: ArtifactKind
    scene: int = -1
    r2_key: str
    provider: str | None = None
    cost_usd: float = 0.0
    checks: dict | None = None  # DB에는 JSON 문자열로 저장
    content_hash: str | None = None


class EvalRow(Row):
    job_id: str
    rubric_version: str
    item: str
    score: float
    judge: Literal["llm", "gemini", "rule", "human"]
    note: str | None = None


class Decision(Row):
    id: int | None = None
    job_id: str | None = None
    role: str
    action: str
    reason: str | None = None
    created_at: str | None = None


class Approval(Row):
    job_id: str
    decision: Literal["approved", "rejected", "redo"]
    reason: str | None = None
    decided_at: str | None = None


class Publication(Row):
    job_id: str
    platform: Literal["youtube", "instagram", "naver_kit"]
    post_id: str | None = None
    status: Literal["pending", "ok", "failed"]
    published_at: str | None = None
    error: str | None = None


class MetricRow(Row):
    job_id: str
    platform: str
    span: Literal["48h", "7d"]
    views: int | None = None
    engaged_views: int | None = None
    avg_view_pct: float | None = None
    subs_gained: int | None = None
    likes: int | None = None
    shares: int | None = None
    comments: int | None = None
    captured_at: str | None = None


class ConfigVersion(Row):
    version: str
    change: str | None = None
    pr_number: int | None = None
    eval_score: float | None = None
    merged_at: str | None = None


class Event(Row):
    id: int | None = None
    kind: str
    payload: str | None = None
    created_at: str | None = None


# ---------------------------------------------------------------- 역할 입출력


class TopicCandidate(BaseModel):
    title: str = Field(max_length=60)
    angle: str
    evidence_url: str | None = None
    score: float = Field(ge=0, le=1)


class ResearchResult(BaseModel):
    """researcher 출력 — 후보 최대 10개, chosen 은 고른 후보의 인덱스."""

    candidates: list[TopicCandidate] = Field(min_length=1, max_length=10)
    chosen: int = Field(default=0, ge=0)
    format_id: str | None = None


class Scene(BaseModel):
    narration: str = Field(max_length=120)
    visual: Literal["stock", "image", "video"]
    query_or_prompt: str
    on_screen_text: str = ""
    target_sec: float = Field(ge=2, le=12)


class Product(BaseModel):
    keyword: str  # 브랜드명이 아닌 쿠팡 검색 키워드
    reason: str = ""


class Storyboard(BaseModel):
    """writer 출력."""

    title: str = Field(max_length=40)
    hook: str = Field(max_length=15)
    scenes: list[Scene] = Field(min_length=4, max_length=7)
    insight: str  # 채널 고유 판단 (비진정성 대응)
    hashtags: list[str] = Field(max_length=5)
    description: str = Field(default="", max_length=300)  # 설명란 본문 2~3줄
    products: list[Product] = Field(default_factory=list, max_length=3)


class SceneAsset(BaseModel):
    scene: int = Field(ge=0)
    audio_key: str
    visual_key: str | None = None  # None 이면 렌더가 단색 배경으로 채운다
    source: str  # 비주얼 공급자 (mock, pexels, placeholder, nano_banana, veo ...)
    duration_sec: float = Field(gt=0)
    cost_usd: float = Field(default=0.0, ge=0)


class AssetManifest(BaseModel):
    """producer 출력 — 장면별 오디오·비주얼 키."""

    scenes: list[SceneAsset] = Field(min_length=1)


class RenderResult(BaseModel):
    """editor(결정론) 출력."""

    final_key: str
    duration_sec: float = Field(gt=0)
    thumb_key: str


QA_ITEMS: tuple[str, ...] = ("hook", "insight", "accuracy", "av_match", "subtitle", "audio", "policy")


class QAReport(BaseModel):
    """critic 출력. passed=False 이고 redo_from=None 이면 자동 수정 불가 → needs_human."""

    scores: dict[str, float]  # hook, insight, accuracy, av_match, subtitle, audio, policy
    passed: bool
    redo_from: Literal["storyboarding", "producing_assets", "rendering"] | None = None
    fixes: list[str] = Field(default_factory=list)


class YouTubeMeta(BaseModel):
    title: str = Field(max_length=100)
    description: str
    tags: list[str] = Field(default_factory=list)


class InstagramMeta(BaseModel):
    caption: str = Field(max_length=2200)


class NaverMeta(BaseModel):
    title: str
    caption: str


class PlatformMeta(BaseModel):
    """publisher(packaging) 출력."""

    youtube: YouTubeMeta
    instagram: InstagramMeta
    naver: NaverMeta
    affiliate: bool = False                 # 대가성 문구를 넣었는지
    contains_synthetic_media: bool = False  # AI 생성 영상 클립을 썼는지 (YouTube 표기)


# ---------------------------------------------------------------- 포트 보조 타입 (2단계 이후 구현)


class WordTiming(BaseModel):
    text: str
    start: float
    end: float


class SceneAudio(BaseModel):
    path: str
    duration: float
    words: list[WordTiming] = Field(default_factory=list)


class VisualSpec(BaseModel):
    scene: int
    kind: Literal["stock", "image", "video"]
    query_or_prompt: str
    target_sec: float


class VisualResult(BaseModel):
    path: str
    kind: Literal["stock", "image", "video"]
    provider: str
    cost_usd: float = 0.0


class MediaRef(BaseModel):
    key: str
    url: str | None = None
