"""FFmpeg 합성: 장면 클립(9:16) + 내레이션 + (선택) BGM + 자막 → final.mp4."""
from __future__ import annotations

from pathlib import Path

from autotube.config import ROOT, Config
from autotube.models import Job, SceneAudio, Script
from autotube.stages.subtitles import build_ass
from autotube.utils import ffmpeg, log, media_duration

PLACEHOLDER_COLORS = ["0x1e293b", "0x0f766e", "0x7c2d12", "0x312e81", "0x365314", "0x831843"]


def _scene_clip(cfg: Config, visual: Path | None, duration: float, out: Path, idx: int) -> None:
    w, h, fps = cfg.get_path("render.width"), cfg.get_path("render.height"), cfg.get_path("render.fps", 30)
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-an"]
    if visual:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}"
        ffmpeg("-stream_loop", "-1", "-i", str(visual), "-t", f"{duration:.3f}", "-vf", vf, *enc, str(out))
    else:
        color = PLACEHOLDER_COLORS[idx % len(PLACEHOLDER_COLORS)]
        ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}:d={duration:.3f}", *enc, str(out))


def render(cfg: Config, job: Job, script: Script, audios: list[SceneAudio], visuals: list[Path | None]) -> Path:
    scene_dir = job.dir / "scenes"
    scene_dir.mkdir(exist_ok=True)

    # 1) 장면 클립 — 길이는 해당 장면 음성 + 여유 0.2초
    clips, durations = [], []
    for i, (audio, visual) in enumerate(zip(audios, visuals)):
        clip = scene_dir / f"v_{i:02d}.mp4"
        _scene_clip(cfg, visual, audio.duration + 0.2, clip, i)
        clips.append(clip)
        durations.append(media_duration(clip))  # 프레임 반올림 반영한 실제 길이

    # 2) 영상 이어붙이기
    (scene_dir / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "video.mp4", cwd=scene_dir)

    # 3) 내레이션 이어붙이기 — 장면 영상 길이에 맞춰 무음 패딩(싱크 유지)
    inputs, parts = [], []
    for i, (audio, dur) in enumerate(zip(audios, durations)):
        inputs += ["-i", audio.path]
        parts.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=whole_dur={dur:.3f},atrim=0:{dur:.3f}[a{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(audios))) + f"concat=n={len(audios)}:v=0:a=1[out]"
    narration = job.dir / "narration.wav"
    ffmpeg(*inputs, "-filter_complex", graph, "-map", "[out]", str(narration))

    # 4) 자막
    offsets, t = [], 0.0
    for d in durations:
        offsets.append(t)
        t += d
    build_ass(cfg, script, audios, offsets, durations, job.dir / "subs.ass")

    # 5) 최종 합성 (+BGM 덕킹 없이 낮은 볼륨 믹스)
    args = ["-i", "scenes/video.mp4", "-i", "narration.wav"]
    bgm = cfg.get_path("render.bgm")
    if bgm and (ROOT / bgm).exists():
        args += ["-stream_loop", "-1", "-i", str(ROOT / bgm)]
        vol = cfg.get_path("render.bgm_volume", 0.12)
        afilter = f"[2:a]volume={vol}[b];[1:a][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    else:
        afilter = "[1:a]anull[a]"
    ffmpeg(
        *args,
        "-filter_complex", f"[0:v]ass=subs.ass[v];{afilter}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
        "final.mp4",
        cwd=job.dir,
    )
    log.info("렌더 완료: %s (%.1f초)", job.video_path, media_duration(job.video_path))
    return job.video_path
