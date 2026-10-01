"""채널 설정(config/channel.yaml)과 .env 로드. v0 autotube.config 를 대체한다."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHANNEL_PATH = ROOT / "config" / "channel.yaml"
DATA_DIR = ROOT / "data"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """외부 의존성 없이 .env를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_channel(path: Path = CHANNEL_PATH) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def get_path(cfg: dict, dotted: str, default: Any = None) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def formats(cfg: dict) -> list[dict]:
    return list(cfg.get("formats") or [])


def format_by_id(cfg: dict, format_id: str | None) -> dict:
    fmts = formats(cfg)
    for f in fmts:
        if f["id"] == format_id:
            return f
    return fmts[0] if fmts else {"id": "default", "name": "기본", "structure": ""}


def font(cfg: dict) -> str:
    name = get_path(cfg, "render.font", "auto")
    if name != "auto":
        return name
    return "Apple SD Gothic Neo" if sys.platform == "darwin" else "Noto Sans CJK KR"
