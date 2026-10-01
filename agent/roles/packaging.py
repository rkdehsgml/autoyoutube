"""packaging — 플랫폼별 제목·설명·캡션 + 대가성 문구 + AI 표기 플래그 (코드, v0 metadata.build 이전).

LLM publisher 는 5단계(게시)에서 붙인다.
"""
from __future__ import annotations

from agent.core.channel import get_path
from agent.core.models import (
    AssetManifest, InstagramMeta, NaverMeta, PlatformMeta, Storyboard, YouTubeMeta,
)
from agent.core.ports import StepContext, StepOutput
from agent.roles.deps import RoleDeps, load_json, put_json

AI_VIDEO_PROVIDERS = frozenset({"veo", "kling", "hailuo"})  # 이 공급자 클립을 쓰면 합성 미디어 표기


def normalize_tags(tags: list[str], limit: int = 5) -> list[str]:
    seen, out = set(), []
    for t in tags:
        t = "#" + t.lstrip("#").replace(" ", "")
        if len(t) > 1 and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:limit]


def build_meta(channel: dict, board: Storyboard, used_ai: bool = False) -> PlatformMeta:
    affiliate = bool(get_path(channel, "disclosure.enable_affiliate", False) and board.products)
    disclosure = get_path(channel, "disclosure.coupang", "") if affiliate else ""
    tags = normalize_tags(board.hashtags)
    product_lines = [f"- {p.keyword}: {p.reason}" if p.reason else f"- {p.keyword}" for p in board.products]
    description = board.description or board.title
    body = [description, "", f"고르는 기준: {board.insight}"] if board.insight else [description]

    yt = ([disclosure, ""] if disclosure else []) + body
    if product_lines:
        yt += ["", "영상 속 제품", *product_lines]
        if affiliate:
            yt += ["제품 링크는 채널 프로필 링크에서 확인하세요."]
    yt += ["", " ".join(tags)]

    ig_tags = tags + (list(get_path(channel, "disclosure.instagram_tags", []) or []) if affiliate else [])
    ig = ([disclosure, ""] if disclosure else []) + [board.title, ""] + body
    if product_lines:
        ig += ["", *product_lines] + (["링크는 프로필에서"] if affiliate else [])
    ig += ["", " ".join(ig_tags)]

    naver = ([disclosure] if disclosure else []) + body + [" ".join(tags)]
    return PlatformMeta(
        youtube=YouTubeMeta(title=board.title[:100], description="\n".join(yt).strip()[:4900],
                            tags=[t.lstrip("#") for t in tags]),
        instagram=InstagramMeta(caption="\n".join(ig).strip()[:2150]),
        naver=NaverMeta(title=board.title, caption="\n".join(naver).strip()),
        affiliate=affiliate,
        contains_synthetic_media=used_ai,
    )


async def run(ctx: StepContext, deps: RoleDeps) -> StepOutput:
    board: Storyboard = load_json(ctx, "storyboard", Storyboard)
    try:
        manifest: AssetManifest | None = load_json(ctx, "manifest", AssetManifest)
    except RuntimeError:
        manifest = None
    used_ai = bool(manifest and any(s.source in AI_VIDEO_PROVIDERS for s in manifest.scenes))
    meta = build_meta(deps.channel, board, used_ai)
    put_json(ctx, "meta.json", meta, "meta", provider="code")
    return StepOutput(output=meta)

