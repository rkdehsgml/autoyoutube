"""단계 오케스트레이션: generate(주제→final.mp4+metadata) / publish(승인된 job → 플랫폼)."""
from __future__ import annotations

import os
from pathlib import Path

from autotube.config import OUTPUTS_DIR, Config
from autotube.models import Job, Script
from autotube.stages import metadata, topics
from autotube.stages.render import render
from autotube.stages.script import generate_script
from autotube.stages.tts import synthesize_scenes
from autotube.stages.visuals import collect
from autotube.utils import log, require_ffmpeg


def _rotate_format(cfg: Config, outputs_dir: Path) -> str:
    """포맷 로테이션 — 템플릿 반복 방지."""
    formats = cfg.get_path("formats")
    done = len(list(outputs_dir.glob("*/job.json")))
    return formats[done % len(formats)]["id"]


def _github_output(**values: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def generate(cfg: Config, topic: str | None = None, format_id: str | None = None,
             from_queue: bool = False, outputs_dir: Path = OUTPUTS_DIR) -> Job:
    require_ffmpeg()
    outputs_dir.mkdir(parents=True, exist_ok=True)
    if from_queue:
        row = topics.next_topic()
        if not row:
            raise RuntimeError("주제 큐가 비었습니다: data/topics.csv에 추가하거나 텔레그램 /new 로 주문하세요.")
        topic, format_id = row["topic"], format_id or row.get("format") or None
    if not topic:
        raise ValueError("주제가 필요합니다 (--topic 또는 --from-queue).")
    format_id = format_id or _rotate_format(cfg, outputs_dir)

    job = Job.new(topic, format_id, outputs_dir)
    job.save()
    log.info("job %s | %s | %s", job.id, topic, format_id)

    script = generate_script(cfg, topic, format_id, topics.recent_titles(outputs_dir))
    job.write_json("script.json", script.to_dict())

    audios = synthesize_scenes(cfg, [s.narration for s in script.scenes], job.dir / "audio")
    visuals, used_ai = collect(cfg, script.scenes, job.dir / "visuals")
    render(cfg, job, script, audios, visuals)
    job.write_json("metadata.json", metadata.build(cfg, script, used_ai))

    if from_queue:
        topics.mark(topic, "done", job.id)
    _github_output(job_id=job.id)
    return job


def publish(cfg: Config, job_dir: Path, platforms: list[str]) -> dict:
    job = Job.load(job_dir)
    meta = job.read_json("metadata.json")
    if not job.video_path.exists():
        raise FileNotFoundError(job.video_path)
    results: dict[str, str] = {}

    if "youtube" in platforms:
        from autotube.publish import youtube
        results["youtube"] = f"https://youtu.be/{youtube.upload(cfg, job.video_path, meta)}"

    if "instagram" in platforms:
        from autotube.publish import instagram, storage
        url = storage.upload_public(job.video_path, f"reels/{job.id}.mp4")
        results["instagram"] = instagram.publish_reel(url, meta["instagram"]["caption"])

    job.write_json("publish_result.json", results)
    return results


def load_script(job_dir: Path) -> Script:
    return Script.from_dict(Job.load(job_dir).read_json("script.json"))
