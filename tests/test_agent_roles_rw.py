"""researcher·writer 실제 역할 코드 경로 — 가짜 query 로 확인."""
import asyncio
import json
from pathlib import Path

import pytest
from fakes import FakeQuery, research_output, storyboard_output

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.store_sqlite import SqliteStore
from agent.core.models import Topic
from agent.core.ports import StepContext
from agent.core.settings import load_roles
from agent.core.text import norm_hash
from agent.roles import researcher, writer
from agent.roles.deps import RoleDeps
from agent.tools.base import ToolContext
from agent.tools.topic_bank import build_topic_bank_tool


@pytest.fixture
def env(tmp_path):
    store = SqliteStore(":memory:")
    blobs = LocalBlobStore(tmp_path / "media")
    return store, blobs


def _ctx(store, blobs, job, step, role):
    return StepContext(job=store.get_job(job.id), store=store, blobs=blobs, step=step, role=role,
                       role_config=load_roles()[role])


def _payload(fq, idx=0):
    prompt = fq.calls[idx][0]
    return json.loads(prompt[prompt.index("{"):])


def test_researcher_picks_topic_and_format(env):
    store, blobs = env
    store.add_topic(Topic(id="OLD", title="장마철 곰팡이", norm_hash=norm_hash("장마철 곰팡이"),
                          source="web", status="used"))
    job = store.create_job("cron")
    fq = FakeQuery({"ResearchResult": research_output(chosen=1, format_id="myth_fact")})
    out = asyncio.run(researcher.run(_ctx(store, blobs, job, "researching", "researcher"), RoleDeps(query_fn=fq)))
    assert out.job_fields["format_id"] == "myth_fact"
    topic = store.query("SELECT * FROM topics WHERE id = ?", [out.job_fields["topic_id"]])[0]
    assert topic["title"] == "빨래 쉰내 원인" and topic["status"] == "used"
    assert out.cost_usd == pytest.approx(0.01) and out.usage["tokens_in"] == 100
    assert store.artifacts(job.id, "research")[0].r2_key == f"jobs/{job.id}/research.json"
    payload = _payload(fq)
    assert payload["recent_titles"] == ["장마철 곰팡이"]
    assert {f["id"] for f in payload["formats"]} >= {"problem_solution", "myth_fact"}
    opts = fq.options_for("ResearchResult")
    assert "mcp__autotube__topic_bank" in opts.allowed_tools and "WebSearch" in opts.tools


def test_researcher_requested_topic_and_bad_format_falls_back(env):
    store, blobs = env
    job = store.create_job("telegram", requested_topic="보일러 난방비 오해")
    fq = FakeQuery({"ResearchResult": research_output(chosen=9, format_id="nope", requested="보일러 난방비 오해")})
    out = asyncio.run(researcher.run(_ctx(store, blobs, job, "researching", "researcher"), RoleDeps(query_fn=fq)))
    topic = store.query("SELECT * FROM topics WHERE id = ?", [out.job_fields["topic_id"]])[0]
    assert topic["title"] == "보일러 난방비 오해" and topic["source"] == "manual"  # chosen 범위 밖 → 0
    assert out.job_fields["format_id"] == "problem_solution"  # 로테이션 첫 포맷
    assert _payload(fq)["requested_topic"] == "보일러 난방비 오해"


def test_researcher_marks_banked_candidate_used(env):
    store, blobs = env
    store.add_topic(Topic(id="BANK", title="빨래 쉰내 원인", norm_hash=norm_hash("빨래 쉰내 원인"), source="web"))
    job = store.create_job("cron")
    fq = FakeQuery({"ResearchResult": research_output(chosen=1)})
    out = asyncio.run(researcher.run(_ctx(store, blobs, job, "researching", "researcher"), RoleDeps(query_fn=fq)))
    assert out.job_fields["topic_id"] == "BANK"
    assert store.query("SELECT status FROM topics WHERE id = 'BANK'")[0]["status"] == "used"


def test_topic_bank_tool_ops(env, tmp_path):
    store, blobs = env
    job = store.create_job("cron")
    tool = build_topic_bank_tool(ToolContext(job=job, store=store, blobs=blobs, workdir=tmp_path))

    def call(args):
        res = asyncio.run(tool.handler(args))
        return res.get("is_error", False), res["content"][0]["text"]

    is_err, text = call({"op": "put", "title": "욕실 물때 순서", "angle": "순서가 핵심", "score": 3})
    assert not is_err and json.loads(text)["status"] == "new"
    assert json.loads(call({"op": "check", "title": "욕실  물때 순서!"})[1])["duplicate"] is True
    assert json.loads(call({"op": "check", "title": "다른 주제"})[1])["duplicate"] is False
    assert json.loads(call({"op": "recent"})[1])["titles"] == []  # 'new' 후보는 최근 다룬 제목이 아님
    assert call({"op": "check"})[0] is True
    assert call({"op": "delete", "title": "x"})[0] is True
    assert store.query("SELECT score FROM topics")[0]["score"] == 1.0  # 0~1 로 자름


def test_writer_writes_storyboard_and_downgrades_visuals(env):
    store, blobs = env
    store.add_topic(Topic(id="T1", title="제습기 전기세 오해", norm_hash="h", source="web", angle="사용 시간",
                          status="used"))
    job = store.create_job("cron")
    store.transition(job.id, "queued", "researching", topic_id="T1", format_id="myth_fact")
    fq = FakeQuery({"Storyboard": storyboard_output(visual="video")})
    out = asyncio.run(writer.run(_ctx(store, blobs, job, "storyboarding", "writer"), RoleDeps(query_fn=fq)))
    assert all(s.visual == "stock" for s in out.output.scenes)
    saved = json.loads(Path(blobs.local_path(f"jobs/{job.id}/storyboard.json")).read_text(encoding="utf-8"))
    assert saved["scenes"][0]["visual"] == "stock" and saved["products"][0]["keyword"] == "저소음 제습기"
    payload = _payload(fq)
    assert payload["topic"]["title"] == "제습기 전기세 오해"
    assert payload["format"]["id"] == "myth_fact"
    assert payload["target_chars"] == int(45 * 6.5)
    assert payload["available_visuals"] == ["stock"]
    assert fq.options_for("Storyboard").tools == []


def test_writer_requires_topic(env):
    store, blobs = env
    job = store.create_job("cron")
    fq = FakeQuery({"Storyboard": storyboard_output()})
    with pytest.raises(RuntimeError):
        asyncio.run(writer.run(_ctx(store, blobs, job, "storyboarding", "writer"), RoleDeps(query_fn=fq)))
