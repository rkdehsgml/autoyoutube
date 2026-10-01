"""단어 타이밍 도우미."""
from __future__ import annotations

from agent.core.models import WordTiming


def estimate_word_timings(text: str, duration: float) -> list[WordTiming]:
    """타이밍을 주지 않는 TTS용: 글자 수 비례로 어절 시간을 나눈다."""
    words = text.split()
    total = sum(len(w) for w in words) or 1
    t, out = 0.0, []
    for w in words:
        d = duration * len(w) / total
        out.append(WordTiming(text=w, start=round(t, 3), end=round(t + d, 3)))
        t += d
    return out
