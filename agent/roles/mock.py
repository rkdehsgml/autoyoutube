"""가짜 역할 — 외부 API 없이 상태 머신 전체를 돌린다.

키 구조는 R2와 같다 (jobs/{job_id}/research.json, storyboard.json, audio/scene_{i}.mp3, ...).
오디오·영상은 자리표시 바이트이고, 실제 TTS·렌더는 2단계에서 붙는다.
테스트용으로 QA 불합격·일시 오류·비용을 조절할 수 있다.
"""
from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from pydantic import BaseModel

from agent.core.clock import new_ulid
from agent.core.models import (
    QA_ITEMS, Artifact, AssetManifest, InstagramMeta, NaverMeta, PlatformMeta, QAReport, RenderResult,
    ResearchResult, Scene, SceneAsset, Storyboard, Topic, TopicCandidate, YouTubeMeta,
)
from agent.core.ports import RetryableError, StepContext, StepHandler, StepOutput

DEFAULT_TOPICS = [
    ("장마철 원룸 곰팡이 냄새 잡는 법", "problem_solution"),
    ("자취방 겨울 외풍 막는 준비물", "season_checklist"),
    ("가성비 무선청소기 고르는 기준", "price_tier_top3"),
    ("제습기 틀면 전기세 폭탄이라는 오해", "myth_fact"),
    ("욕실 물때 쉽게 없애는 순서", "problem_solution"),
    ("이사 첫날 꼭 챙길 생활용품", "season_checklist"),
    ("가습기 종류별 장단점", "price_tier_top3"),
    ("빨래 쉰내 원인과 해결", "problem_solution"),
    ("보일러 난방비 줄이는 오해와 사실", "myth_fact"),
    ("원룸 수납 늘리는 도구 3가지", "price_tier_top3"),
]

DEFAULT_COSTS = {"researcher": 0.01, "writer": 0.02, "producer": 0.05, "render_video": 0.0,
                 "critic": 0.01, "publisher": 0.005}


def norm_hash(title: str) -> str:
    norm = re.sub(r"[\s\W_]+", "", title.lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _key(job_id: str, name: str) -> str:
    return f"jobs/{job_id}/{name}"


def _put(ctx: StepContext, name: str, data: bytes, content_type: str, kind: str, scene: int = -1,
         provider: str = "mock", cost: float = 0.0, checks: dict | None = None) -> Artifact:
    key = ctx.blobs.put(_key(ctx.job.id, name), data, content_type)
    art = Artifact(job_id=ctx.job.id, kind=kind, scene=scene, r2_key=key, provider=provider, cost_usd=cost,
                   checks=checks, content_hash=hashlib.sha256(data).hexdigest())
    ctx.store.put_artifact(art)
    return art


def _put_json(ctx: StepContext, name: str, model: BaseModel, kind: str) -> Artifact:
    return _put(ctx, name, model.model_dump_json(indent=2).encode("utf-8"), "application/json", kind)


def _load(ctx: StepContext, kind: str, model: type[BaseModel]) -> BaseModel:
    arts = ctx.store.artifacts(ctx.job.id, kind)
    if not arts:
        raise RuntimeError(f"이전 단계 산출물 없음: {kind}")
    with tempfile.TemporaryDirectory() as tmp:
        path = ctx.blobs.get(arts[0].r2_key, Path(tmp) / "a.json")
        return model.model_validate_json(path.read_text(encoding="utf-8"))


class MockRoles:
    """mock 핸들러 모음.

    qa_failures: critic 이 처음 N번 불합격을 낸다 (redo_from 지정 가능, None이면 자동 수정 불가).
    transient: {핸들러: N} — 처음 N번 RetryableError.
    crash: 이 핸들러는 예상 못 한 오류를 낸다.
    costs: 핸들러별 비용(USD) 덮어쓰기.
    """

    def __init__(self, qa_failures: int = 0, redo_from: str | None = "producing_assets",
                 transient: dict[str, int] | None = None, crash: str | None = None,
                 costs: dict[str, float] | None = None):
        self.qa_failures = qa_failures
        self.redo_from = redo_from
        self.transient = dict(transient or {})
        self.crash = crash
        self.costs = {**DEFAULT_COSTS, **(costs or {})}
        self.calls: dict[str, int] = {}

    def handlers(self) -> dict[str, StepHandler]:
        return {name: self._wrap(name, getattr(self, name))
                for name in ("researcher", "writer", "producer", "render_video", "critic", "publisher")}

    def _wrap(self, name: str, fn):
        async def handler(ctx: StepContext) -> StepOutput:
            self.calls[name] = self.calls.get(name, 0) + 1
            if self.crash == name:
                raise RuntimeError(f"mock crash in {name}")
            if self.transient.get(name, 0) > 0:
                self.transient[name] -= 1
                raise RetryableError(f"mock 일시 오류 ({name})")
            out = fn(ctx)
            out.cost_usd = self.costs.get(name, 0.0)
            out.usage = {"tokens_in": 1000, "tokens_out": 200} if ctx.role else {}
            return out
        return handler

    # ------------------------------------------------------------ 역할
    def researcher(self, ctx: StepContext) -> StepOutput:
        requested = (ctx.job.requested_topic or "").strip()
        pool = [(t, f) for t, f in DEFAULT_TOPICS if t != requested]
        cands = [TopicCandidate(title=t, angle=f"{f} 포맷으로 해결 기준 제시", score=round(0.8 - i * 0.05, 2))
                 for i, (t, f) in enumerate(pool)]
        if requested:
            cands.insert(0, TopicCandidate(title=requested[:60], angle="요청 주제", score=0.95))
        result = ResearchResult(candidates=cands[:10], chosen=0,
                                format_id=ctx.job.format_id or dict(DEFAULT_TOPICS).get(cands[0].title,
                                                                                       "problem_solution"))
        chosen = result.candidates[result.chosen]
        topic = ctx.store.add_topic(Topic(id=new_ulid(), title=chosen.title, norm_hash=norm_hash(chosen.title),
                                          source="manual" if requested else "web", angle=chosen.angle,
                                          score=chosen.score, status="used"))
        _put_json(ctx, "research.json", result, "research")
        return StepOutput(output=result, job_fields={"topic_id": topic.id, "format_id": result.format_id})

    def writer(self, ctx: StepContext) -> StepOutput:
        title = ctx.store.query("SELECT title FROM topics WHERE id = ?", [ctx.job.topic_id])[0]["title"]
        scenes = [
            Scene(narration=f"{title}, 이것부터 확인하세요.", visual="stock", query_or_prompt="small room problem",
                  on_screen_text="이것부터!", target_sec=3),
            Scene(narration="원인은 대부분 습기와 환기 부족입니다.", visual="stock", query_or_prompt="humid window",
                  target_sec=5),
            Scene(narration="첫째, 물건을 벽에서 한 뼘 띄우세요.", visual="image", query_or_prompt="furniture gap wall",
                  on_screen_text="한 뼘 띄우기", target_sec=6),
            Scene(narration="둘째, 하루 두 번 십 분씩 맞통풍을 만드세요.", visual="stock",
                  query_or_prompt="open window breeze", target_sec=6),
            Scene(narration="제 기준은 하나, 원인을 먼저 없애고 도구는 그다음입니다.", visual="stock",
                  query_or_prompt="tidy room", target_sec=5),
        ]
        board = Storyboard(title=title[:40], hook="이것부터 확인!", scenes=scenes,
                           insight="도구보다 원인 제거가 먼저", hashtags=["#자취", "#생활꿀팁", "#쇼츠"])
        _put_json(ctx, "storyboard.json", board, "storyboard")
        return StepOutput(output=board)

    def producer(self, ctx: StepContext) -> StepOutput:
        board: Storyboard = _load(ctx, "storyboard", Storyboard)
        assets = []
        for i, sc in enumerate(board.scenes):
            audio = _put(ctx, f"audio/scene_{i}.mp3", f"MOCK-AUDIO {sc.narration}".encode(), "audio/mpeg",
                         "audio", scene=i)
            ext = "mp4" if sc.visual == "video" else "png"
            visual = _put(ctx, f"visuals/scene_{i}.{ext}", f"MOCK-VISUAL {sc.query_or_prompt}".encode(),
                          "video/mp4" if ext == "mp4" else "image/png", "visual", scene=i,
                          checks={"ratio_ok": True, "text_ok": True, "issues": []})
            assets.append(SceneAsset(scene=i, audio_key=audio.r2_key, visual_key=visual.r2_key, source="mock",
                                     duration_sec=sc.target_sec))
        return StepOutput(output=AssetManifest(scenes=assets))

    def render_video(self, ctx: StepContext) -> StepOutput:
        board: Storyboard = _load(ctx, "storyboard", Storyboard)
        t, lines = 0.0, []
        for sc in board.scenes:
            lines.append(f"Dialogue: 0,{_ts(t)},{_ts(t + sc.target_sec)},Default,,0,0,0,,{sc.narration}")
            t += sc.target_sec
        subs = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[Events]\n" + "\n".join(lines)
        _put(ctx, "subs.ass", subs.encode("utf-8"), "text/plain", "subs")
        final = _put(ctx, "final.mp4", b"MOCK-FINAL-MP4", "video/mp4", "final")
        thumb = _put(ctx, "thumb.jpg", b"MOCK-THUMB", "image/jpeg", "thumb")
        return StepOutput(output=RenderResult(final_key=final.r2_key, duration_sec=t, thumb_key=thumb.r2_key))

    def critic(self, ctx: StepContext) -> StepOutput:
        n = self.calls.get("critic", 0)
        failing = n <= self.qa_failures
        scores = {item: (0.4 if failing else 0.85) for item in QA_ITEMS}
        report = QAReport(scores=scores, passed=not failing, redo_from=self.redo_from if failing else None,
                          fixes=["자막이 장면 전환과 어긋남"] if failing else [])
        _put_json(ctx, "qa/report.json", report, "qa")
        return StepOutput(output=report)

    def publisher(self, ctx: StepContext) -> StepOutput:
        board: Storyboard = _load(ctx, "storyboard", Storyboard)
        tags = " ".join(board.hashtags)
        meta = PlatformMeta(
            youtube=YouTubeMeta(title=f"{board.title} #shorts"[:100], description=f"{board.insight}\n\n{tags}",
                                tags=[h.lstrip("#") for h in board.hashtags]),
            instagram=InstagramMeta(caption=f"{board.title}\n{board.insight}\n{tags}"),
            naver=NaverMeta(title=board.title, caption=f"{board.insight} {tags}"),
        )
        _put_json(ctx, "meta.json", meta, "meta")
        return StepOutput(output=meta)


def _ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"
