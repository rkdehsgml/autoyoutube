"""FFmpeg 합성: 장면 클립(9:16) + 내레이션 + (선택) BGM + 자막 → final.mp4 + thumb.jpg (v0 에서 이전)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.media.ffmpeg import ffmpeg, log, media_duration
from agent.media.subtitles import SceneMedia, build_ass

PLACEHOLDER_COLORS = ["0x1e293b", "0x0f766e", "0x7c2d12", "0x312e81", "0x365314", "0x831843"]
SCENE_PAD_SEC = 0.2  # 장면 음성 뒤 여유


@dataclass
class RenderOutput:
    final: Path
    thumb: Path
    subs: Path
    duration: float


def _scene_clip(render_cfg: dict, visual: Path | None, duration: float, out: Path, idx: int) -> None:
    w, h, fps = render_cfg.get("width", 1080), render_cfg.get("height", 1920), render_cfg.get("fps", 30)
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-an"]
    if visual:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}"
        ffmpeg("-stream_loop", "-1", "-i", str(visual), "-t", f"{duration:.3f}", "-vf", vf, *enc, str(out))
    else:
        color = PLACEHOLDER_COLORS[idx % len(PLACEHOLDER_COLORS)]
        ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}:d={duration:.3f}", *enc, str(out))


def render(scenes: list[SceneMedia], hook: str, workdir: Path, render_cfg: dict, font: str,
           bgm: Path | None = None, bgm_volume: float = 0.12) -> RenderOutput:
    if not scenes:
        raise ValueError("장면이 없습니다")
    scene_dir = workdir / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)

    # 1) 장면 클립 — 길이는 해당 장면 음성 + 여유
    clips, durations = [], []
    for i, sc in enumerate(scenes):
        clip = scene_dir / f"v_{i:02d}.mp4"
        _scene_clip(render_cfg, sc.visual, sc.duration + SCENE_PAD_SEC, clip, i)
        clips.append(clip)
        durations.append(media_duration(clip))  # 프레임 반올림 반영한 실제 길이

    # 2) 영상 이어붙이기
    (scene_dir / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "video.mp4", cwd=scene_dir)

    # 3) 내레이션 이어붙이기 — 장면 영상 길이에 맞춰 무음 패딩(싱크 유지)
    inputs, parts = [], []
    for i, (sc, dur) in enumerate(zip(scenes, durations)):
        inputs += ["-i", str(sc.audio)]
        parts.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=whole_dur={dur:.3f},"
                     f"atrim=0:{dur:.3f}[a{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(scenes))) + \
        f"concat=n={len(scenes)}:v=0:a=1[out]"
    narration = workdir / "narration.wav"
    ffmpeg(*inputs, "-filter_complex", graph, "-map", "[out]", str(narration))

    # 4) 자막
    offsets, t = [], 0.0
    for d in durations:
        offsets.append(t)
        t += d
    subs = build_ass(scenes, hook, offsets, durations, workdir / "subs.ass", render_cfg, font)

    # 5) 최종 합성 (+BGM 덕킹 없이 낮은 볼륨 믹스)
    args = ["-i", "scenes/video.mp4", "-i", "narration.wav"]
    if bgm and bgm.exists():
        args += ["-stream_loop", "-1", "-i", str(bgm)]
        afilter = f"[2:a]volume={bgm_volume}[b];[1:a][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    else:
        afilter = "[1:a]anull[a]"
    ffmpeg(*args, "-filter_complex", f"[0:v]ass=subs.ass[v];{afilter}", "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", "final.mp4", cwd=workdir)
    final = workdir / "final.mp4"
    duration = media_duration(final)

    # 6) 썸네일 — 훅이 보이는 첫 장면 프레임
    thumb = workdir / "thumb.jpg"
    ffmpeg("-ss", f"{min(1.0, duration / 2):.2f}", "-i", str(final), "-frames:v", "1", "-q:v", "3", str(thumb))
    log.info("렌더 완료: %s (%.1f초)", final, duration)
    return RenderOutput(final=final, thumb=thumb, subs=subs, duration=duration)
