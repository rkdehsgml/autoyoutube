"""researcher — 오늘의 주제를 고른다 (topic_bank + WebSearch)."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from agent.core.channel import formats, get_path
from agent.core.clock import new_ulid
from agent.core.models import ResearchResult, Topic
from agent.core.ports import StepContext, StepOutput
from agent.core.role_runner import RoleSpec, load_prompt, run_role
from agent.core.text import norm_hash
from agent.roles.deps import RoleDeps, put_json, with_tool_cost
from agent.tools.base import ToolContext
from agent.tools.topic_bank import build_topic_bank_tool, recent_titles


def rotate_format(ctx: StepContext, channel: dict) -> str:
    """포맷 로테이션 — 템플릿 반복 방지 (지금까지 만든 job 수 기준)."""
    fmts = formats(channel)
    if not fmts:
        return "default"
    n = ctx.store.query("SELECT COUNT(*) AS n FROM jobs WHERE format_id IS NOT NULL")[0]["n"]
    return fmts[n % len(fmts)]["id"]


def build_payload(ctx: StepContext, deps: RoleDeps) -> dict:
    ch = deps.channel
    return {
        "today": date.today().isoformat(),
        "channel": {k: get_path(ch, f"channel.{k}") for k in ("name", "niche", "audience", "tone")},
        "formats": [{"id": f["id"], "name": f.get("name", ""), "structure": f.get("structure", "")}
                    for f in formats(ch)],
        "requested_topic": ctx.job.requested_topic,
        "requested_format": ctx.job.format_id,
        "recent_titles": recent_titles(ctx.store),
    }


async def run(ctx: StepContext, deps: RoleDeps) -> StepOutput:
    if ctx.role_config is None:
        raise RuntimeError("researcher 역할 설정이 없습니다 (config/roles.yaml)")
    with tempfile.TemporaryDirectory() as tmp:
        tctx = ToolContext(job=ctx.job, store=ctx.store, blobs=ctx.blobs, workdir=Path(tmp))
        spec = RoleSpec(config=ctx.role_config, system_prompt=load_prompt("researcher"),
                        output_model=ResearchResult, mcp_tools=[build_topic_bank_tool(tctx)],
                        builtin_tools=["WebSearch"])
        try:
            res = await run_role(spec, build_payload(ctx, deps), query_fn=deps.query_fn)
        except Exception as e:
            raise with_tool_cost(e, tctx.cost_usd)

    result: ResearchResult = res.output
    if result.chosen >= len(result.candidates):
        result.chosen = 0
    chosen = result.candidates[result.chosen]
    valid_formats = {f["id"] for f in formats(deps.channel)}
    format_id = ctx.job.format_id or (result.format_id if result.format_id in valid_formats else None) \
        or rotate_format(ctx, deps.channel)
    result.format_id = format_id

    source = "manual" if ctx.job.requested_topic else "web"
    topic = ctx.store.add_topic(Topic(id=new_ulid(), title=chosen.title, norm_hash=norm_hash(chosen.title),
                                      source=source, angle=chosen.angle, evidence_url=chosen.evidence_url,
                                      score=chosen.score, status="used"))
    if topic.status != "used":  # topic_bank put 으로 먼저 저장된 후보였던 경우
        ctx.store.mark_topic(topic.id, "used")
    put_json(ctx, "research.json", result, "research", provider=ctx.role_config.model)
    return StepOutput(output=result, cost_usd=res.cost_usd + tctx.cost_usd, usage=res.usage,
                      job_fields={"topic_id": topic.id, "format_id": format_id})
