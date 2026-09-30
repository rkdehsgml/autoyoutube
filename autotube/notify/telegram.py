"""텔레그램: 완성 영상 미리보기 + [승인]/[반려] 버튼 → 폰에서 1탭 승인.

버튼 콜백은 workers/telegram-approval(Cloudflare Worker)가 받아 GitHub publish 워크플로를 실행한다.
콜백 데이터 형식: "ok|<job_id>|<run_id>" / "no|<job_id>|<run_id>" (64바이트 이하)
"""
from __future__ import annotations

import html
import json
import os

import requests

from autotube.models import Job
from autotube.utils import log


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"


def enabled() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_text(text: str) -> None:
    if not enabled():
        log.info("[telegram 미설정] %s", text)
        return
    requests.post(_api("sendMessage"), data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}, timeout=30).raise_for_status()


def send_preview(job: Job) -> None:
    meta = job.read_json("metadata.json")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    flags = []
    if meta.get("affiliate"):
        flags.append("대가성 문구 포함")
    if meta.get("contains_synthetic_media"):
        flags.append("AI 합성 표기")
    products = ", ".join(p["keyword"] for p in meta.get("products", [])) or "없음"
    caption = (
        f"<b>{html.escape(meta['title'])}</b>\n"
        f"주제: {html.escape(job.topic)} · 포맷: {job.format_id}\n"
        f"제품: {html.escape(products)}\n"
        f"{' · '.join(flags) or '표기 없음'}\n"
        f"job: <code>{job.id}</code>"
    )
    if not run_id:
        caption += f"\n로컬 생성 — 승인: python -m autotube publish --job outputs/{job.id}"

    if not enabled():
        log.info("[telegram 미설정] 미리보기 생략: %s", job.video_path)
        return

    data = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": caption[:1024], "parse_mode": "HTML", "supports_streaming": "true"}
    if run_id:
        data["reply_markup"] = json.dumps({"inline_keyboard": [[
            {"text": "승인 · 업로드", "callback_data": f"ok|{job.id}|{run_id}"},
            {"text": "반려", "callback_data": f"no|{job.id}|{run_id}"},
        ]]})
    with open(job.video_path, "rb") as f:  # 봇 업로드 한도 50MB — 쇼츠는 보통 충분
        requests.post(_api("sendVideo"), data=data, files={"video": f}, timeout=300).raise_for_status()
    # 네이버 클립에 붙여넣을 문구를 따로 보내 폰에서 바로 복사
    send_text("[네이버 클립용 문구]\n" + meta["naver_clip"]["text"])
