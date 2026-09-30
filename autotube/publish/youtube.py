"""YouTube 업로드 (Data API v3 videos.insert).

주의: 감사(audit)를 받지 않은 API 프로젝트로 올린 영상은 비공개로 고정된다.
복무 중에는 publish.youtube_privacy: private 으로 테스트하고, 공개 전환 전에 감사를 신청한다.
"""
from __future__ import annotations

from pathlib import Path

from autotube.config import Config, env
from autotube.utils import log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=env("YT_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env("YT_CLIENT_ID"),
        client_secret=env("YT_CLIENT_SECRET"),
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(cfg: Config, video: Path, meta: dict) -> str:
    from googleapiclient.http import MediaFileUpload

    yt = meta["youtube"]
    body = {
        "snippet": {
            "title": yt["title"],
            "description": yt["description"],
            "tags": yt["tags"],
            "categoryId": cfg.get_path("publish.youtube_category_id", "26"),
            "defaultLanguage": "ko",
            "defaultAudioLanguage": "ko",
        },
        "status": {
            "privacyStatus": cfg.get_path("publish.youtube_privacy", "private"),
            "selfDeclaredMadeForKids": bool(cfg.get_path("publish.made_for_kids", False)),
            # 현실적인 AI 합성 장면을 썼을 때만 true (YouTube 'AI 사용' 표기)
            "containsSyntheticMedia": bool(meta.get("contains_synthetic_media", False)),
        },
    }
    request = _client().videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("YouTube 업로드 %d%%", int(status.progress() * 100))
    video_id = response["id"]
    log.info("YouTube 업로드 완료: https://youtu.be/%s (%s)", video_id, body["status"]["privacyStatus"])
    return video_id
