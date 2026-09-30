"""파이프라인 단계 사이를 오가는 데이터 구조."""
from __future__ import annotations

import json
import random
import re
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
JOB_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9]{4}$")


@dataclass
class Scene:
    narration: str
    search_query: str = ""
    on_screen_text: str = ""
    use_ai_clip: bool = False
    ai_clip_prompt: str = ""


@dataclass
class Product:
    keyword: str
    reason: str = ""


@dataclass
class Script:
    title: str
    hook: str
    scenes: list[Scene]
    products: list[Product] = field(default_factory=list)
    insight: str = ""
    hashtags: list[str] = field(default_factory=list)
    description: str = ""
    topic: str = ""
    format_id: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Script":
        return cls(
            title=d["title"].strip(),
            hook=d.get("hook", "").strip(),
            scenes=[Scene(**{k: v for k, v in s.items() if k in Scene.__dataclass_fields__}) for s in d["scenes"]],
            products=[Product(**{k: v for k, v in p.items() if k in Product.__dataclass_fields__}) for p in d.get("products", [])],
            insight=d.get("insight", ""),
            hashtags=d.get("hashtags", []),
            description=d.get("description", ""),
            topic=d.get("topic", ""),
            format_id=d.get("format_id", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WordTiming:
    text: str
    start: float  # 초, 장면 오디오 기준
    end: float


@dataclass
class SceneAudio:
    path: str
    duration: float
    words: list[WordTiming]


@dataclass
class Job:
    id: str
    topic: str
    format_id: str
    dir: Path

    @classmethod
    def new(cls, topic: str, format_id: str, outputs_dir: Path) -> "Job":
        stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        job_id = f"{stamp}-{suffix}"
        job_dir = outputs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return cls(job_id, topic, format_id, job_dir)

    @classmethod
    def load(cls, job_dir: Path) -> "Job":
        job_id = job_dir.name
        if not JOB_ID_RE.match(job_id):
            raise ValueError(f"잘못된 job id: {job_id}")
        meta = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        return cls(job_id, meta["topic"], meta["format_id"], job_dir)

    def save(self) -> None:
        (self.dir / "job.json").write_text(
            json.dumps({"id": self.id, "topic": self.topic, "format_id": self.format_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def video_path(self) -> Path:
        return self.dir / "final.mp4"

    def write_json(self, name: str, data) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_json(self, name: str):
        return json.loads((self.dir / name).read_text(encoding="utf-8"))
