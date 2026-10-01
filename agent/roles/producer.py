"""producer — 장면별 음성·비주얼 에셋을 만든다.

live: LLM 이 도구(tts_synthesize·stock_search·check_asset)를 부르며 비주얼 검색어를 고친다.
mock/결정론: LLM 없이 같은 도구 함수를 순서대로 부른다.
어느 쪽이든 마지막에 reconcile() 이 실제 저장된 산출물로 매니페스트를 다시 만든다
(LLM 이 적은 키는 믿지 않음). 빠진 음성은 직접 합성하고, 못 찾은 비주얼은 단색 배경으로 둔다.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from agent.core.models import AssetManifest, QAReport, SceneAsset, Storyboard
from agent.core.ports import StepContext, StepOutput
from agent.core.role_runner import RoleSpec, load_prompt, run_role
from agent.roles.deps import RoleDeps, load_json, put_json, with_tool_cost
from agent.tools.base import ToolContext
from agent.tools.media import build_media_tools, stock, synthesize


def board_hash(board: Storyboard) -> str:
    return hashlib.sha256(board.model_dump_json().encode("utf-8")).hexdigest()[:16]


def build_payload(ctx: StepContext, board: Storyboard, deps: RoleDeps) -> dict:
    payload = {
        "voice": deps.voice,
        "scenes": [{"scene": i, "narration": s.narration, "visual": s.visual, "query_or_prompt": s.query_or_prompt,
                    "target_sec": s.target_sec} for i, s in enumerate(board.scenes)],
    }
    if ctx.job.qa_rounds > 0:  # QA 재작업이면 지난 지적 사항을 넘긴다
        try:
            payload["qa_fixes"] = load_json(ctx, "qa", QAReport).fixes
        except RuntimeError:
            pass
    return payload


async def reconcile(tctx: ToolContext, board: Storyboard, available: tuple[str, ...]) -> tuple[AssetManifest, list]:
    """저장된 산출물 기준으로 매니페스트를 만든다. (빠진 것 보정 목록도 돌려준다)"""
    store, job = tctx.store, tctx.job
    bhash = board_hash(board)
    fixed: list[str] = []
    audios = {a.scene: a for a in store.artifacts(job.id, "audio")}
    scenes = []
    for i, sc in enumerate(board.scenes):
        if i not in audios:
            fixed.append(f"audio:{i}")
        await synthesize(tctx, i)  # 같은 텍스트면 캐시, 바뀌었으면 다시 합성
        visual = next((a for a in store.artifacts(job.id, "visual") if a.scene == i), None)
        if visual is not None and (visual.checks or {}).get("board") not in (None, bhash):
            visual = None  # 스토리보드가 바뀌기 전 비주얼
        if visual is None and sc.visual in available and tctx.stock is not None:
            try:
                res = await stock(tctx, i, sc.query_or_prompt)
            except Exception as e:  # 네트워크 오류 등은 단색 배경으로 계속
                res = {"found": False, "reason": f"{type(e).__name__}: {e}"}
            if res.get("found"):
                visual = next((a for a in store.artifacts(job.id, "visual") if a.scene == i), None)
                fixed.append(f"visual:{i}")
        if visual is not None:
            visual.checks = {**(visual.checks or {}), "board": bhash}
            store.put_artifact(visual)
        audio_art = next(a for a in store.artifacts(job.id, "audio") if a.scene == i)
        scenes.append(SceneAsset(
            scene=i, audio_key=audio_art.r2_key, visual_key=visual.r2_key if visual else None,
            source=(visual.provider or "stock") if visual else "placeholder",
            duration_sec=float((audio_art.checks or {}).get("duration") or sc.target_sec),
            cost_usd=float(audio_art.cost_usd or 0) + (float(visual.cost_usd or 0) if visual else 0.0),
        ))
    return AssetManifest(scenes=scenes), fixed


async def run(ctx: StepContext, deps: RoleDeps, use_llm: bool = True) -> StepOutput:
    board: Storyboard = load_json(ctx, "storyboard", Storyboard)
    cost, usage, claimed = 0.0, {}, None
    with tempfile.TemporaryDirectory() as tmp:
        tctx = ToolContext(job=ctx.job, store=ctx.store, blobs=ctx.blobs, workdir=Path(tmp), storyboard=board,
                           tts=deps.tts, voice=deps.voice, stock=deps.stock)
        if use_llm:
            if ctx.role_config is None:
                raise RuntimeError("producer 역할 설정이 없습니다 (config/roles.yaml)")
            spec = RoleSpec(config=ctx.role_config, system_prompt=load_prompt("producer"),
                            output_model=AssetManifest, mcp_tools=build_media_tools(tctx))
            try:
                res = await run_role(spec, build_payload(ctx, board, deps), query_fn=deps.query_fn)
            except Exception as e:
                raise with_tool_cost(e, tctx.cost_usd)
            cost, usage, claimed = res.cost_usd, res.usage, res.output
        try:
            manifest, fixed = await reconcile(tctx, board, deps.available_visuals)
        except Exception as e:
            raise with_tool_cost(e, tctx.cost_usd + cost)
        tool_cost = tctx.cost_usd

    if claimed is not None:
        real = {(s.scene, s.audio_key, s.visual_key) for s in manifest.scenes}
        said = {(s.scene, s.audio_key, s.visual_key) for s in claimed.scenes}
        if real != said:
            ctx.store.add_decision(ctx.job.id, "producer", "manifest_corrected",
                                   f"LLM 매니페스트 {len(said - real)}건을 저장된 산출물 기준으로 고침")
    if fixed and use_llm:
        ctx.store.add_decision(ctx.job.id, "producer", "filled_missing", ", ".join(fixed))
    put_json(ctx, "manifest.json", manifest, "manifest")
    return StepOutput(output=manifest, cost_usd=cost + tool_cost, usage=usage)
