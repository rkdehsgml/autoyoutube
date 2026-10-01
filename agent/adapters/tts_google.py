"""GoogleTTS — Google Cloud Text-to-Speech (Chirp 3 HD 등). v0 에서 이전."""
from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

from agent.core.models import SceneAudio
from agent.media.ffmpeg import media_duration
from agent.media.timing import estimate_word_timings

# TODO(decision): 음성별 단가 확인 — Chirp 3 HD 를 100만 자당 약 $30 으로 가정 (docs/candidates.md 재확인 대상)
DEFAULT_COST_PER_CHAR = 30 / 1_000_000


class GoogleTTS:
    name = "google"

    def __init__(self, voice: str, api_key: str | None = None, cost_per_char: float = DEFAULT_COST_PER_CHAR):
        self.voice = voice
        self.api_key = api_key or os.getenv("GOOGLE_TTS_API_KEY", "")
        self.cost_per_char = cost_per_char
        if not self.api_key:
            raise RuntimeError("GOOGLE_TTS_API_KEY 가 없습니다 (.env 또는 GitHub Secrets)")

    def synthesize(self, text: str, voice: str, out: Path) -> SceneAudio:
        r = requests.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            headers={"x-goog-api-key": self.api_key},
            json={"input": {"text": text}, "voice": {"languageCode": "ko-KR", "name": voice or self.voice},
                  "audioConfig": {"audioEncoding": "MP3"}},
            timeout=60,
        )
        r.raise_for_status()
        out.write_bytes(base64.b64decode(r.json()["audioContent"]))
        duration = media_duration(out)
        return SceneAudio(path=str(out), duration=duration, words=estimate_word_timings(text, duration))
