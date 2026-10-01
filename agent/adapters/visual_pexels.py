"""PexelsStock — 세로형 스톡 영상 검색·다운로드. v0 에서 이전."""
from __future__ import annotations

import os
from pathlib import Path

import requests

from agent.core.models import VisualResult, VisualSpec

PEXELS_SEARCH = "https://api.pexels.com/videos/search"


def pick_file(video: dict) -> dict | None:
    """세로형이면서 1080x1920 에 가장 가까운 파일."""
    files = [f for f in video.get("video_files", [])
             if f.get("height") and f.get("width") and f["height"] > f["width"]]
    if not files:
        return None
    return min(files, key=lambda f: abs(f["height"] - 1920))


class PexelsStock:
    name = "pexels"
    kind = "stock"

    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.api_key = api_key or os.getenv("PEXELS_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("PEXELS_API_KEY 가 없습니다")
        self.http = session or requests.Session()

    def create(self, spec: VisualSpec, out: Path, exclude: set | None = None) -> VisualResult | None:
        exclude = exclude if exclude is not None else set()
        r = self.http.get(PEXELS_SEARCH, headers={"Authorization": self.api_key},
                          params={"query": spec.query_or_prompt, "orientation": "portrait", "per_page": 10},
                          timeout=30)
        r.raise_for_status()
        for video in r.json().get("videos", []):
            if video.get("id") in exclude:
                continue
            f = pick_file(video)
            if not f:
                continue
            with self.http.get(f["link"], stream=True, timeout=120) as dl:
                dl.raise_for_status()
                with open(out, "wb") as fh:
                    for chunk in dl.iter_content(1 << 20):
                        fh.write(chunk)
            exclude.add(video["id"])
            return VisualResult(path=str(out), kind="stock", provider="pexels", cost_usd=0.0,
                                source_url=video.get("url", ""))
        return None
