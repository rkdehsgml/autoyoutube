"""비주얼 수집: 장면별 세로 스톡 영상(Pexels). 실패하면 None → 렌더 단계에서 단색 배경."""
from __future__ import annotations

from pathlib import Path

import requests

from autotube.config import Config, env
from autotube.models import Scene
from autotube.utils import log

PEXELS_SEARCH = "https://api.pexels.com/videos/search"


def _pick_file(video: dict) -> dict | None:
    """세로형이면서 1080x1920에 가장 가까운 파일."""
    files = [f for f in video.get("video_files", []) if f.get("height") and f.get("width") and f["height"] > f["width"]]
    if not files:
        return None
    return min(files, key=lambda f: abs(f["height"] - 1920))


def _pexels(query: str, out: Path, used: set[int]) -> Path | None:
    r = requests.get(
        PEXELS_SEARCH,
        headers={"Authorization": env("PEXELS_API_KEY")},
        params={"query": query, "orientation": "portrait", "per_page": 10},
        timeout=30,
    )
    r.raise_for_status()
    for video in r.json().get("videos", []):
        if video["id"] in used:
            continue
        f = _pick_file(video)
        if not f:
            continue
        used.add(video["id"])
        with requests.get(f["link"], stream=True, timeout=120) as dl:
            dl.raise_for_status()
            with open(out, "wb") as fh:
                for chunk in dl.iter_content(1 << 20):
                    fh.write(chunk)
        return out
    return None


def generate_ai_clip(prompt: str, out: Path) -> Path:
    """TODO: Veo / Kling / Hailuo 등 AI 영상 API 연결. 연결 전에는 스톡으로 대체된다."""
    raise NotImplementedError("AI 영상 공급자가 아직 연결되지 않았습니다 (providers.ai_video).")


def collect(cfg: Config, scenes: list[Scene], visual_dir: Path) -> tuple[list[Path | None], bool]:
    """반환: (장면별 영상 경로, AI 합성 영상 사용 여부)."""
    provider = cfg.get_path("providers.visuals", "pexels")
    visual_dir.mkdir(exist_ok=True)
    used: set[int] = set()
    paths: list[Path | None] = []
    used_ai = False
    for i, scene in enumerate(scenes):
        out = visual_dir / f"scene_{i:02d}.mp4"
        path = None
        if scene.use_ai_clip and cfg.get_path("providers.ai_video", "none") != "none":
            try:
                path = generate_ai_clip(scene.ai_clip_prompt or scene.narration, out)
                used_ai = True
            except NotImplementedError as e:
                log.warning("%s → 스톡으로 대체", e)
        if path is None and provider == "pexels" and scene.search_query:
            try:
                path = _pexels(scene.search_query, out, used)
            except Exception as e:  # 네트워크·키 문제는 단색 배경으로 계속 진행
                log.warning("Pexels 실패(%s): %s", scene.search_query, e)
        paths.append(path)
    log.info("비주얼: %d/%d개 확보", sum(p is not None for p in paths), len(paths))
    return paths, used_ai
