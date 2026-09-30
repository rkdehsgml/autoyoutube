"""Instagram Reels 게시 (Graph API Content Publishing).

흐름: 공개 URL의 영상 → REELS 컨테이너 생성 → 처리 완료 대기 → media_publish.
프로페셔널(비즈니스/크리에이터) 계정 + 액세스 토큰 필요. 영상은 공개 URL이어야 한다(storage.py).
"""
from __future__ import annotations

import os
import time

import requests

from autotube.config import env
from autotube.utils import log


def _base() -> str:
    host = os.getenv("IG_GRAPH_HOST", "https://graph.facebook.com")
    return f"{host}/{os.getenv('IG_GRAPH_VERSION', 'v23.0')}"


def publish_reel(video_url: str, caption: str, timeout_sec: int = 600) -> str:
    user_id, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    r = requests.post(
        f"{_base()}/{user_id}/media",
        data={"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true", "access_token": token},
        timeout=60,
    )
    r.raise_for_status()
    container_id = r.json()["id"]

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        s = requests.get(f"{_base()}/{container_id}", params={"fields": "status_code", "access_token": token}, timeout=30)
        s.raise_for_status()
        code = s.json().get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"Instagram 처리 실패: {s.json()}")
        time.sleep(10)
    else:
        raise TimeoutError("Instagram 컨테이너 처리 대기 시간 초과")

    p = requests.post(f"{_base()}/{user_id}/media_publish", data={"creation_id": container_id, "access_token": token}, timeout=60)
    p.raise_for_status()
    media_id = p.json()["id"]
    log.info("Instagram 릴스 게시 완료: %s", media_id)
    return media_id
