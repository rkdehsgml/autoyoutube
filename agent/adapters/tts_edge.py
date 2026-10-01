"""EdgeTTS — 무료 Microsoft Edge 음성 (단어 경계 타이밍 포함). v0 에서 이전."""
from __future__ import annotations

import asyncio
from pathlib import Path

from agent.core.models import SceneAudio, WordTiming
from agent.media.ffmpeg import media_duration
from agent.media.timing import estimate_word_timings

TICKS_PER_SEC = 10_000_000  # edge-tts 오프셋 단위(100ns)


class EdgeTTS:
    name = "edge"
    cost_per_char = 0.0

    def __init__(self, rate: str = "+0%"):
        self.rate = rate

    async def _stream(self, text: str, voice: str, out: Path) -> list[WordTiming]:
        import edge_tts

        comm = edge_tts.Communicate(text, voice, rate=self.rate, boundary="WordBoundary")
        words: list[WordTiming] = []
        with open(out, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / TICKS_PER_SEC
                    words.append(WordTiming(text=chunk["text"], start=start,
                                            end=start + chunk["duration"] / TICKS_PER_SEC))
        return words

    def synthesize(self, text: str, voice: str, out: Path) -> SceneAudio:
        # 도구는 asyncio.to_thread 로 부르므로 여기서 새 이벤트 루프를 써도 된다
        words = asyncio.run(self._stream(text, voice, out))
        duration = media_duration(out)
        return SceneAudio(path=str(out), duration=duration, words=words or estimate_word_timings(text, duration))
