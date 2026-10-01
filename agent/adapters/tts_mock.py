"""MockTTS — 무음 mp3 (내레이션 길이를 글자 수로 추정). 외부 호출 없음."""
from __future__ import annotations

from pathlib import Path

from agent.core.models import SceneAudio
from agent.media.ffmpeg import ffmpeg, media_duration
from agent.media.timing import estimate_word_timings


class MockTTS:
    name = "mock"
    cost_per_char = 0.0

    def synthesize(self, text: str, voice: str, out: Path) -> SceneAudio:
        duration = max(1.5, len(text.replace(" ", "")) / 6.5)
        ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{duration:.2f}",
               "-c:a", "libmp3lame", "-q:a", "9", str(out))
        return SceneAudio(path=str(out), duration=media_duration(out),
                          words=estimate_word_timings(text, duration))
