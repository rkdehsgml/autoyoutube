"""공용 헬퍼: 로깅, FFmpeg 실행, 길이 측정."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("autotube")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool}이 없습니다. 맥: brew install ffmpeg / 우분투: apt-get install ffmpeg")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    log.debug("$ %s", " ".join(map(str, cmd)))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"명령 실패 ({proc.returncode}): {' '.join(map(str, cmd))}\n{proc.stderr[-2000:]}")


def ffmpeg(*args: str, cwd: Path | None = None) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], cwd=cwd)


def media_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def video_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)
