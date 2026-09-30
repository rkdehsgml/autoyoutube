"""ASS 자막: 단어 타이밍을 짧은 덩어리로 묶어 화면 중하단에 표시 + 상단 훅 문구."""
from __future__ import annotations

from pathlib import Path

from autotube.config import Config
from autotube.models import SceneAudio, Script

# edge-tts 단어 경계에는 문장부호가 빠지므로 한국어 종결어미로도 끊는다
SENTENCE_END = (".", "?", "!", ",", "니다", "세요", "어요", "아요", "해요", "까요", "죠")


def _ts(sec: float) -> str:
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _chunks(words, max_chars: int):
    """(start, end, text) 덩어리 — 글자 수 한도나 문장 끝에서 끊는다."""
    buf, out = [], []
    for w in words:
        buf.append(w)
        length = sum(len(x.text) for x in buf)
        if length >= max_chars or w.text.endswith(SENTENCE_END):
            out.append(buf)
            buf = []
    if buf:
        out.append(buf)
    return [(c[0].start, c[-1].end, " ".join(x.text for x in c)) for c in out]


def build_ass(cfg: Config, script: Script, audios: list[SceneAudio], offsets: list[float],
              durations: list[float], out: Path) -> Path:
    w, h = cfg.get_path("render.width", 1080), cfg.get_path("render.height", 1920)
    font, size = cfg.font, cfg.get_path("render.font_size", 78)
    margin_v = cfg.get_path("render.subtitle_margin_v", 620)
    max_chars = cfg.get_path("render.max_chars_per_line", 14)

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        # 색상은 &HAABBGGRR — 흰 글자 + 검은 외곽선 / 훅은 노란 글자
        f"Style: Sub,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,0,2,70,70,{margin_v},1",
        f"Style: Hook,{font},{size + 10},&H0000E6FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8,0,8,70,70,260,1",
        f"Style: Label,{font},{size - 14},&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,3,14,0,8,70,70,300,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if script.hook:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(min(2.8, durations[0]))},Hook,,0,0,0,,{_esc(script.hook)}")

    for scene, audio, offset, dur in zip(script.scenes, audios, offsets, durations):
        chunks = _chunks(audio.words, max_chars)
        for j, (start, end, text) in enumerate(chunks):
            # 다음 덩어리 시작까지 유지해서 깜빡임 방지, 장면 끝을 넘지 않게
            nxt = chunks[j + 1][0] if j + 1 < len(chunks) else dur
            lines.append(f"Dialogue: 0,{_ts(offset + start)},{_ts(offset + min(max(end, nxt), dur))},Sub,,0,0,0,,{_esc(text)}")
        if scene.on_screen_text:
            lines.append(f"Dialogue: 1,{_ts(offset)},{_ts(offset + dur)},Label,,0,0,0,,{_esc(scene.on_screen_text)}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
