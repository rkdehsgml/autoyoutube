"""writer — 주제·포맷으로 스토리보드를 쓴다 (도구 없음)."""
from __future__ import annotations

from agent.core.channel import format_by_id, get_path
from agent.core.models import ResearchResult, Storyboard
from agent.core.ports import StepContext, StepOutput
from agent.core.role_runner import RoleSpec, load_prompt, run_role
from agent.roles.deps import RoleDeps, load_json, put_json
from agent.tools.topic_bank import recent_titles

CHARS_PER_SEC = 6.5  # 한국어 내레이션 약 6~7자/초


def build_payload(ctx: StepContext, deps: RoleDeps) -> dict:
    ch = deps.channel
    rows = ctx.store.query("SELECT title, angle, evidence_url FROM topics WHERE id = ?", [ctx.job.topic_id])
    if not rows:
        raise RuntimeError("주제가 없습니다 (researcher 단계 확인)")
    topic = rows[0]
    fmt = format_by_id(ch, ctx.job.format_id)
    seconds = int(get_path(ch, "channel.target_seconds", 45))
    try:
        research: ResearchResult | None = load_json(ctx, "research", ResearchResult)
    except RuntimeError:
        research = None
    return {
        "channel": {k: get_path(ch, f"channel.{k}") for k in ("name", "niche", "audience", "tone")},
        "format": {"id": fmt["id"], "name": fmt.get("name", ""), "structure": fmt.get("structure", "")},
        "topic": topic,
        "other_candidates": [c.title for c in research.candidates][:5] if research else [],
        "target_seconds": seconds,
        "target_chars": int(seconds * CHARS_PER_SEC),
        "available_visuals": list(deps.available_visuals),
        "recent_titles": recent_titles(ctx.store, exclude_id=ctx.job.topic_id),
    }


async def run(ctx: StepContext, deps: RoleDeps) -> StepOutput:
    if ctx.role_config is None:
        raise RuntimeError("writer 역할 설정이 없습니다 (config/roles.yaml)")
    spec = RoleSpec(config=ctx.role_config, system_prompt=load_prompt("writer"), output_model=Storyboard)
    res = await run_role(spec, build_payload(ctx, deps), query_fn=deps.query_fn)
    board: Storyboard = res.output
    allowed = set(deps.available_visuals)
    for scene in board.scenes:  # 아직 못 만드는 비주얼은 스톡으로 내린다
        if scene.visual not in allowed:
            scene.visual = "stock"
    put_json(ctx, "storyboard.json", board, "storyboard", provider=ctx.role_config.model)
    return StepOutput(output=board, cost_usd=res.cost_usd, usage=res.usage)
