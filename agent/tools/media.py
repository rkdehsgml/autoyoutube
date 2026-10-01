"""producer 도구 — tts_synthesize · stock_search · check_asset.

순수 함수(테스트·결정론 producer 가 직접 부름)와 @tool 래퍼(LLM producer 가 부름)로 나뉜다.
멱등 키(job·scene·입력 해시)가 같으면 다시 만들지 않고 저장된 결과를 돌려준다.
막히는 작업(ffmpeg·HTTP·edge-tts)은 asyncio.to_thread 로 돌린다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from agent.core.models import Artifact, VisualSpec, WordTiming
from agent.core.text import input_hash
from agent.media.ffmpeg import media_duration, video_size
from agent.tools.base import ToolContext, err, ok

MIN_PORTRAIT_HEIGHT = 1280  # TODO(decision): 스톡 최소 세로 해상도 — 720p 세로(1280) 이상 허용


def words_key(audio_key: str) -> str:
    return audio_key.rsplit(".", 1)[0] + ".words.json"


def _existing(tctx: ToolContext, kind: str, scene: int, key_hash: str) -> Artifact | None:
    for a in tctx.store.artifacts(tctx.job.id, kind):
        if a.scene == scene and (a.checks or {}).get("input_hash") == key_hash and tctx.blobs.exists(a.r2_key):
            return a
    return None


def _check_scene(tctx: ToolContext, scene: int) -> None:
    n = tctx.scene_count()
    if not 0 <= scene < n:
        raise ValueError(f"scene 은 0~{n - 1} 이어야 합니다 (받은 값 {scene})")


async def synthesize(tctx: ToolContext, scene: int) -> dict:
    """장면 내레이션을 음성으로 만든다. 텍스트는 스토리보드에서만 가져온다 (LLM이 대본을 바꾸지 못하게)."""
    _check_scene(tctx, scene)
    if tctx.tts is None:
        raise RuntimeError("TTS 공급자가 설정되지 않았습니다")
    text = tctx.storyboard.scenes[scene].narration
    provider = getattr(tctx.tts, "name", type(tctx.tts).__name__)
    key_hash = input_hash(tctx.job.id, scene, text, tctx.voice, provider)
    hit = _existing(tctx, "audio", scene, key_hash)
    if hit:
        return {"scene": scene, "audio_key": hit.r2_key, "duration": hit.checks.get("duration"), "cached": True}

    out = tctx.workdir / f"scene_{scene}.mp3"
    audio = await asyncio.to_thread(tctx.tts.synthesize, text, tctx.voice, out)
    cost = len(text) * float(getattr(tctx.tts, "cost_per_char", 0.0) or 0.0)
    tctx.add_cost(cost)
    key = tctx.blobs.put(tctx.key(f"audio/scene_{scene}.mp3"), out, "audio/mpeg")
    words = [w.model_dump() for w in audio.words]
    tctx.blobs.put(words_key(key), json.dumps(words, ensure_ascii=False).encode("utf-8"), "application/json")
    tctx.store.put_artifact(Artifact(
        job_id=tctx.job.id, kind="audio", scene=scene, r2_key=key, provider=provider, cost_usd=cost,
        checks={"input_hash": key_hash, "duration": round(audio.duration, 3), "words": len(words)},
        content_hash=hashlib.sha256(out.read_bytes()).hexdigest(),
    ))
    return {"scene": scene, "audio_key": key, "duration": round(audio.duration, 3), "cached": False}


async def stock(tctx: ToolContext, scene: int, query: str) -> dict:
    """세로형 스톡 영상을 찾아 저장한다. 못 찾으면 found=False."""
    _check_scene(tctx, scene)
    query = (query or "").strip()
    if not query:
        raise ValueError("query 가 필요합니다")
    provider = getattr(tctx.stock, "name", "placeholder") if tctx.stock else "placeholder"
    key_hash = input_hash(tctx.job.id, scene, query, provider)
    hit = _existing(tctx, "visual", scene, key_hash)
    if hit:
        return {"scene": scene, "found": True, "visual_key": hit.r2_key, "cached": True}
    if tctx.stock is None:
        return {"scene": scene, "found": False, "source": "placeholder", "reason": "스톡 공급자 없음"}

    spec = VisualSpec(scene=scene, kind="stock", query_or_prompt=query,
                      target_sec=tctx.storyboard.scenes[scene].target_sec)
    out = tctx.workdir / f"visual_{scene}_{key_hash[:6]}.mp4"
    res = await asyncio.to_thread(tctx.stock.create, spec, out, tctx.used_stock_ids)
    if res is None:
        return {"scene": scene, "found": False, "source": provider, "reason": "검색 결과 없음"}
    tctx.add_cost(res.cost_usd)
    key = tctx.blobs.put(tctx.key(f"visuals/scene_{scene}.mp4"), Path(res.path), "video/mp4")
    tctx.store.put_artifact(Artifact(
        job_id=tctx.job.id, kind="visual", scene=scene, r2_key=key, provider=res.provider, cost_usd=res.cost_usd,
        checks={"input_hash": key_hash, "query": query, "source_url": res.source_url},
        content_hash=hashlib.sha256(Path(res.path).read_bytes()).hexdigest(),
    ))
    return {"scene": scene, "found": True, "visual_key": key, "source_url": res.source_url, "cached": False}


async def check(tctx: ToolContext, key: str) -> dict:
    """비주얼 비율·해상도·길이 검사. text_ok(화면 글자 OCR)는 3단계."""
    prefix = tctx.key("")
    if not key.startswith(prefix):
        raise ValueError("이 job 의 키만 검사할 수 있습니다")
    if not tctx.blobs.exists(key):
        raise ValueError(f"키 없음: {key}")
    local = tctx.blobs.get(key, tctx.workdir / ("check_" + Path(key).name))
    w, h = await asyncio.to_thread(video_size, local)
    duration = await asyncio.to_thread(media_duration, local)
    issues = []
    ratio_ok = h > w
    if not ratio_ok:
        issues.append("세로형이 아님")
    if h < MIN_PORTRAIT_HEIGHT:
        issues.append(f"세로 해상도 {h}px < {MIN_PORTRAIT_HEIGHT}px")
    if duration < 1.0:
        issues.append("1초 미만")
    result = {"key": key, "ratio_ok": ratio_ok, "resolution": f"{w}x{h}", "duration": round(duration, 2),
              "text_ok": None, "issues": issues}
    for a in tctx.store.artifacts(tctx.job.id, "visual"):  # 검사 결과를 artifacts.checks 에 남긴다
        if a.r2_key == key:
            a.checks = {**(a.checks or {}), "ratio_ok": ratio_ok, "resolution": result["resolution"],
                        "issues": issues}
            tctx.store.put_artifact(a)
    return result


def load_words(tctx_or_blobs, audio_key: str, workdir: Path) -> list[WordTiming]:
    blobs = getattr(tctx_or_blobs, "blobs", tctx_or_blobs)
    key = words_key(audio_key)
    if not blobs.exists(key):
        return []
    path = blobs.get(key, workdir / Path(key).name)
    return [WordTiming(**w) for w in json.loads(path.read_text(encoding="utf-8"))]


# ---------------------------------------------------------------- @tool 래퍼

def build_media_tools(tctx: ToolContext) -> list:
    from claude_agent_sdk import tool

    async def guard(coro):
        try:
            return ok(await coro)
        except (ValueError, RuntimeError) as e:
            return err(str(e))
        except Exception as e:  # 네트워크 등 — LLM 이 다른 키워드로 재시도할 수 있게 오류로 돌려준다
            return err(f"{type(e).__name__}: {e}")

    @tool("tts_synthesize", "장면 내레이션을 음성으로 만든다 (텍스트는 스토리보드에서 가져옴). 반환: audio_key, duration",
          {"type": "object", "properties": {"scene": {"type": "integer"}}, "required": ["scene"]})
    async def tts_synthesize(args: dict) -> dict:
        return await guard(synthesize(tctx, int(args.get("scene", -1))))

    @tool("stock_search", "세로형 스톡 영상을 찾아 저장한다. query 는 영어 2~4단어. 반환: found, visual_key",
          {"type": "object", "properties": {"scene": {"type": "integer"}, "query": {"type": "string"}},
           "required": ["scene", "query"]})
    async def stock_search(args: dict) -> dict:
        return await guard(stock(tctx, int(args.get("scene", -1)), args.get("query", "")))

    @tool("check_asset", "저장된 비주얼의 비율·해상도·길이를 검사한다. 반환: ratio_ok, resolution, issues",
          {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]})
    async def check_asset(args: dict) -> dict:
        return await guard(check(tctx, args.get("key", "")))

    return [tts_synthesize, stock_search, check_asset]
