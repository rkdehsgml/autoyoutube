"""channel.yaml + .env 로드."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "channel.yaml"
PROMPT_PATH = ROOT / "config" / "prompts" / "script_ko.md"
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"


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


class Config(dict):
    """점 표기법으로 읽는 설정: cfg.get_path("providers.llm")."""

    def get_path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set_path(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def format_by_id(self, format_id: str | None) -> dict:
        formats = self.get_path("formats", [])
        for f in formats:
            if f["id"] == format_id:
                return f
        return formats[0]

    @property
    def font(self) -> str:
        font = self.get_path("render.font", "auto")
        if font != "auto":
            return font
        return "Apple SD Gothic Neo" if sys.platform == "darwin" else "Noto Sans CJK KR"


def load_config(path: Path = CONFIG_PATH) -> Config:
    load_dotenv()
    with open(path, encoding="utf-8") as f:
        cfg = Config(yaml.safe_load(f))
    # 환경변수가 설정 파일보다 우선
    if os.getenv("LLM_PROVIDER"):
        cfg.set_path("providers.llm", os.environ["LLM_PROVIDER"])
    if os.getenv("LLM_MODEL"):
        cfg.set_path("providers.llm_model", os.environ["LLM_MODEL"])
    return cfg


def env(name: str, required: bool = True) -> str:
    value = os.getenv(name, "")
    if required and not value:
        raise RuntimeError(f"환경변수 {name}이(가) 없습니다. .env 또는 GitHub Secrets에 추가하세요.")
    return value
