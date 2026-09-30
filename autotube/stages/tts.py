"""음성 합성: 장면별 오디오 + 단어 타이밍(자막 싱크용)."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import requests

from autotube.config import Config, env
from autotube.models import SceneAudio, WordTiming
from autotube.utils import ffmpeg, log, media_duration

TICKS_PER_SEC = 10_000_000  # edge-tts 오프셋 단위(100ns)


def estimate_word_timings(text: str, duration: float) -> list[WordTiming]:
    """타이밍을 주지 않는 TTS용: 글자 수 비례로 어절 시간을 나눈다."""
    words = text.split()
    total = sum(len(w) for w in words) or 1
    t, out = 0.0, []
    for w in words:
        d = duration * len(w) / total
        out.append(WordTiming(w, round(t, 3), round(t + d, 3)))
        t += d
    return out


async def _edge_async(text: str, voice: str, rate: str, out: Path) -> list[WordTiming]:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words: list[WordTiming] = []
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS_PER_SEC
                words.append(WordTiming(chunk["text"], start, start + chunk["duration"] / TICKS_PER_SEC))
    return words


def _edge(cfg: Config, text: str, out: Path) -> SceneAudio:
    voice = cfg.get_path("providers.tts_voice", "ko-KR-SunHiNeural")
    rate = cfg.get_path("providers.tts_rate", "+0%")
    words = asyncio.run(_edge_async(text, voice, rate, out))
    duration = media_duration(out)
    return SceneAudio(str(out), duration, words or estimate_word_timings(text, duration))


def _google(cfg: Config, text: str, out: Path) -> SceneAudio:
    r = requests.post(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        headers={"x-goog-api-key": env("GOOGLE_TTS_API_KEY")},
        json={
            "input": {"text": text},
            "voice": {"languageCode": "ko-KR", "name": cfg.get_path("providers.google_voice")},
            "audioConfig": {"audioEncoding": "MP3"},
        },
        timeout=60,
    )
    r.raise_for_status()
    out.write_bytes(base64.b64decode(r.json()["audioContent"]))
    duration = media_duration(out)
    return SceneAudio(str(out), duration, estimate_word_timings(text, duration))


def _mock(cfg: Config, text: str, out: Path) -> SceneAudio:
    duration = max(1.5, len(text.replace(" ", "")) / 6.5)
    ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{duration:.2f}", "-c:a", "libmp3lame", "-q:a", "9", str(out))
    return SceneAudio(str(out), media_duration(out), estimate_word_timings(text, duration))


PROVIDERS = {"edge": _edge, "google": _google, "mock": _mock}


def synthesize_scenes(cfg: Config, narrations: list[str], audio_dir: Path) -> list[SceneAudio]:
    provider = cfg.get_path("providers.tts", "edge")
    audio_dir.mkdir(exist_ok=True)
    log.info("음성 합성: %s, %d개 장면", provider, len(narrations))
    return [PROVIDERS[provider](cfg, text, audio_dir / f"scene_{i:02d}.mp3") for i, text in enumerate(narrations)]
