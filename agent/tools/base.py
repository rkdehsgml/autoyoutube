"""도구 공용 — 도구는 job 하나에 묶인 ToolContext 를 받는다 (다른 job에 쓸 수 없게 job_id 를 입력으로 받지 않음)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.core.models import Job, Storyboard
from agent.core.ports import BlobStore, Store


@dataclass
class ToolContext:
    job: Job
    store: Store
    blobs: BlobStore
    workdir: Path
    storyboard: Storyboard | None = None
    tts: Any = None            # TTSProvider
    voice: str = ""
    stock: Any = None          # VisualProvider (stock)
    cost_usd: float = 0.0      # 도구가 쓴 비용 (유료 TTS 등) — 역할 비용에 합산
    used_stock_ids: set = field(default_factory=set)
    log: list[dict] = field(default_factory=list)

    def key(self, name: str) -> str:
        return f"jobs/{self.job.id}/{name}"

    def add_cost(self, usd: float) -> None:
        self.cost_usd += float(usd or 0.0)

    def scene_count(self) -> int:
        return len(self.storyboard.scenes) if self.storyboard else 0


def ok(data: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}


def err(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "is_error": True}
