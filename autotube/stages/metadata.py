"""플랫폼별 제목·설명·캡션 + 대가성 문구 + AI 표기 플래그."""
from __future__ import annotations

import csv
from pathlib import Path

from autotube.config import DATA_DIR, Config
from autotube.models import Script


def _links(path: Path = DATA_DIR / "coupang_links.csv") -> dict[str, str]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["keyword"].strip(): r["url"].strip() for r in csv.DictReader(f) if r.get("url")}


def _tags(tags: list[str], limit: int = 5) -> list[str]:
    seen, out = set(), []
    for t in tags:
        t = "#" + t.lstrip("#").replace(" ", "")
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:limit]


def build(cfg: Config, script: Script, used_ai: bool) -> dict:
    affiliate = bool(cfg.get_path("disclosure.enable_affiliate", False) and script.products)
    disclosure = cfg.get_path("disclosure.coupang", "") if affiliate else ""
    links = _links()
    products = [{"keyword": p.keyword, "reason": p.reason, "url": links.get(p.keyword, "")} for p in script.products]
    tags = _tags(script.hashtags)

    product_lines = [f"- {p['keyword']}: {p['reason']}" for p in products]
    body = [script.description, "", f"고르는 기준: {script.insight}"] if script.insight else [script.description]

    yt_desc = [disclosure, ""] if disclosure else []
    yt_desc += body
    if products:
        yt_desc += ["", "영상 속 제품"] + product_lines
        if affiliate:
            yt_desc += ["제품 링크는 채널 프로필 링크에서 확인하세요."]
    yt_desc += ["", " ".join(tags)]

    ig_tags = tags + (cfg.get_path("disclosure.instagram_tags", []) if affiliate else [])
    ig_caption = ([disclosure, ""] if disclosure else []) + [script.title, ""] + body
    if products:
        ig_caption += [""] + product_lines + (["링크는 프로필에서"] if affiliate else [])
    ig_caption += ["", " ".join(ig_tags)]

    return {
        "title": script.title,
        "affiliate": affiliate,
        "contains_synthetic_media": used_ai,
        "products": products,
        "youtube": {
            "title": script.title[:100],
            "description": "\n".join(yt_desc).strip()[:4900],
            "tags": [t.lstrip("#") for t in tags],
        },
        "instagram": {"caption": "\n".join(ig_caption).strip()[:2150]},
        "naver_clip": {"text": "\n".join(([disclosure] if disclosure else []) + [script.title] + body + [" ".join(tags)]).strip()},
    }
