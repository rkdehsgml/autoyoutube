"""editor — 렌더링 (LLM 없음, 결정론). 매니페스트에 있는 에셋만 쓴다."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path

from agent.core.channel import ROOT, font, get_path
from agent.core.models import Artifact, AssetManifest, RenderResult, Storyboard
from agent.core.ports import StepContext, StepOutput
from agent.media.ffmpeg import media_duration
from agent.media.render import render
from agent.media.subtitles import SceneMedia
from agent.media.timing import estimate_word_timings
from agent.roles.deps import RoleDeps, load_json
from agent.tools.media import load_words


def _put(ctx: StepContext, name: str, src: Path, content_type: str, kind: str) -> str:
    key = ctx.blobs.put(f"jobs/{ctx.job.id}/{name}", src, content_type)
    ctx.store.put_artifact(Artifact(job_id=ctx.job.id, kind=kind, r2_key=key, provider="ffmpeg",
                                    content_hash=hashlib.sha256(src.read_bytes()).hexdigest()))
    return key


async def run(ctx: StepContext, deps: RoleDeps) -> StepOutput:
    board: Storyboard = load_json(ctx, "storyboard", Storyboard)
    manifest: AssetManifest = load_json(ctx, "manifest", AssetManifest)
    render_cfg = dict(deps.channel.get("render") or {})
    bgm_rel = get_path(deps.channel, "render.bgm") or ""
    bgm = (ROOT / bgm_rel) if bgm_rel else None

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        scenes: list[SceneMedia] = []
        for asset in sorted(manifest.scenes, key=lambda s: s.scene):
            sc = board.scenes[asset.scene]
            audio = ctx.blobs.get(asset.audio_key, work / f"a_{asset.scene}.mp3")
            duration = media_duration(audio)
            words = load_words(ctx.blobs, asset.audio_key, work) or estimate_word_timings(sc.narration, duration)
            visual = ctx.blobs.get(asset.visual_key, work / f"v_{asset.scene}.mp4") if asset.visual_key else None
            scenes.append(SceneMedia(narration=sc.narration, audio=audio, duration=duration, words=words,
                                     visual=visual, on_screen_text=sc.on_screen_text))
        out = await asyncio.to_thread(render, scenes, board.hook, work, render_cfg, font(deps.channel), bgm,
                                      float(render_cfg.get("bgm_volume", 0.12)))
        final_key = _put(ctx, "final.mp4", out.final, "video/mp4", "final")
        thumb_key = _put(ctx, "thumb.jpg", out.thumb, "image/jpeg", "thumb")
        _put(ctx, "subs.ass", out.subs, "text/plain", "subs")
    return StepOutput(output=RenderResult(final_key=final_key, duration_sec=out.duration, thumb_key=thumb_key))
