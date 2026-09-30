"""운영 설정(settings 테이블)과 역할 설정(config/roles.yaml)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent.core.ports import Store

ROOT = Path(__file__).resolve().parents[2]
ROLES_PATH = ROOT / "config" / "roles.yaml"

# settings 테이블에 값이 없을 때 쓰는 기본값 (텔레그램으로 바꾸는 값은 D1 settings 에 둔다)
DEFAULT_SETTINGS: dict[str, str] = {
    "daily_quota": "1",
    "paused": "false",
    "job_budget_usd": "1.0",
    # TODO(decision): 월 상한 기본값 — 시나리오 A(하루 1편 약 $20/월)에 여유를 둔 $30 가정.
    "monthly_budget_usd": "30",
    "platforms": "youtube,instagram,naver_kit",
}

PUBLISH_TOOLS = frozenset({"publish_youtube", "publish_instagram", "send_naver_kit"})


@dataclass(frozen=True)
class RuntimeSettings:
    daily_quota: int
    paused: bool
    job_budget_usd: float
    monthly_budget_usd: float
    platforms: tuple[str, ...]

    @classmethod
    def from_store(cls, store: Store) -> "RuntimeSettings":
        def get(key: str) -> str:
            return store.get_setting(key) or DEFAULT_SETTINGS[key]

        return cls(
            daily_quota=int(get("daily_quota")),
            paused=get("paused").strip().lower() in ("1", "true", "yes", "on"),
            job_budget_usd=float(get("job_budget_usd")),
            monthly_budget_usd=float(get("monthly_budget_usd")),
            platforms=tuple(p.strip() for p in get("platforms").split(",") if p.strip()),
        )


@dataclass(frozen=True)
class RoleConfig:
    name: str
    model: str | None
    max_turns: int
    max_budget_usd: float
    tools: tuple[str, ...] = ()
    gated_tools: tuple[str, ...] = field(default_factory=tuple)


def load_roles(path: Path = ROLES_PATH) -> dict[str, RoleConfig]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    roles: dict[str, RoleConfig] = {}
    for name, d in (data.get("roles") or {}).items():
        tools = tuple(d.get("tools") or ())
        leaked = PUBLISH_TOOLS & set(tools)
        if leaked:
            raise ValueError(f"게시 도구는 allowed_tools 에 둘 수 없습니다: {name} {sorted(leaked)}")
        roles[name] = RoleConfig(
            name=name,
            model=d.get("model"),
            max_turns=int(d["max_turns"]),
            max_budget_usd=float(d["max_budget_usd"]),
            tools=tools,
            gated_tools=tuple(d.get("gated_tools") or ()),
        )
    return roles
