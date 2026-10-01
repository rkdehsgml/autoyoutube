"""실제 역할이 공유하는 의존성 묶음과 공용 도우미."""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent.core.channel import load_channel
from agent.core.models import Artifact
from agent.core.ports import CostCarryingError, StepContext
from agent.core.role_runner import QueryFn


@dataclass
class RoleDeps:
    channel: dict = field(default_factory=load_channel)
    query_fn: QueryFn | None = None   # None → claude_agent_sdk.query (실제 호출)
    tts: Any = None                   # TTSProvider
    voice: str = "ko-KR-SunHiNeural"
    stock: Any = None                 # VisualProvider (stock) — None 이면 단색 배경
    available_visuals: tuple[str, ...] = ("stock",)  # image·video 생성은 7단계


def put_json(ctx: StepContext, name: str, model: BaseModel, kind: str, provider: str | None = None) -> Artifact:
    data = model.model_dump_json(indent=2).encode("utf-8")
    key = ctx.blobs.put(f"jobs/{ctx.job.id}/{name}", data, "application/json")
    art = Artifact(job_id=ctx.job.id, kind=kind, r2_key=key, provider=provider,
                   content_hash=hashlib.sha256(data).hexdigest())
    ctx.store.put_artifact(art)
    return art


def load_json(ctx: StepContext, kind: str, model: type[BaseModel]) -> BaseModel:
    arts = ctx.store.artifacts(ctx.job.id, kind)
    if not arts:
        raise RuntimeError(f"이전 단계 산출물 없음: {kind}")
    with tempfile.TemporaryDirectory() as tmp:
        path = ctx.blobs.get(arts[0].r2_key, Path(tmp) / "a.json")
        return model.model_validate_json(path.read_text(encoding="utf-8"))


def with_tool_cost(e: BaseException, tool_cost: float) -> BaseException:
    """역할이 실패해도 도구 비용까지 오케스트레이터에 넘긴다."""
    if isinstance(e, CostCarryingError):
        e.cost_usd = float(e.cost_usd or 0.0) + float(tool_cost or 0.0)
    return e
