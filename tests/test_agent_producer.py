"""producer 역할 — 결정론 경로와 LLM 경로(가짜 query), 매니페스트 보정."""
import asyncio
import json

import pytest
from fakes import FakeQuery, manifest_output, result_message, storyboard_output
from test_agent_media_tools import FakeStock, PaidTTS

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.store_sqlite import SqliteStore
from agent.adapters.tts_mock import MockTTS
from agent.core.models import QAReport, Storyboard
from agent.core.ports import RetryableError, StepContext
from agent.core.settings import load_roles
from agent.roles import producer
from agent.roles.deps import RoleDeps, put_json


@pytest.fixture
def env(tmp_path):
    store = SqliteStore(":memory:")
    blobs = LocalBlobStore(tmp_path / "media")
    job = store.create_job("manual")
    return store, blobs, job


def _ctx(store, blobs, job, board=None):
    ctx = StepContext(job=store.get_job(job.id), store=store, blobs=blobs, step="producing_assets", role="producer",
                      role_config=load_roles()["producer"])
    if board is not None:
        put_json(ctx, "storyboard.json", board, "storyboard")
    return ctx


def test_deterministic_producer_builds_manifest(env):
    store, blobs, job = env
    board = Storyboard.model_validate(storyboard_output())
    deps = RoleDeps(tts=MockTTS(), stock=FakeStock(missing={2}))
    out = asyncio.run(producer.run(_ctx(store, blobs, job, board), deps, use_llm=False))
    m = out.output
    assert [s.scene for s in m.scenes] == [0, 1, 2, 3, 4]
    assert m.scenes[2].visual_key is None and m.scenes[2].source == "placeholder"
    assert m.scenes[0].source == "fakestock" and m.scenes[0].duration_sec > 1
    assert all(blobs.exists(s.audio_key) for s in m.scenes)
    assert store.artifacts(job.id, "manifest")[0].r2_key == f"jobs/{job.id}/manifest.json"
    assert out.cost_usd == 0 and not store.query("SELECT * FROM decisions")


def test_llm_producer_options_and_manifest_correction(env):
    store, blobs, job = env
    board = Storyboard.model_validate(storyboard_output())
    bogus = manifest_output(job.id)
    bogus["scenes"][0]["visual_key"] = "jobs/x/made-up.mp4"
    fq = FakeQuery({"AssetManifest": result_message(bogus, cost=0.04)})
    deps = RoleDeps(query_fn=fq, tts=PaidTTS(), stock=FakeStock())
    out = asyncio.run(producer.run(_ctx(store, blobs, job, board), deps))
    opts = fq.options_for("AssetManifest")
    assert opts.allowed_tools == ["mcp__autotube__tts_synthesize", "mcp__autotube__stock_search",
                                  "mcp__autotube__check_asset"]  # image·video 생성은 아직 노출 안 됨
    assert opts.tools == []
    tts_cost = sum(len(s.narration) for s in board.scenes) * 0.001
    assert out.cost_usd == pytest.approx(0.04 + tts_cost)  # LLM + 유료 TTS
    assert all(s.visual_key and s.visual_key.startswith(f"jobs/{job.id}/") for s in out.output.scenes)
    actions = {r["action"] for r in store.query("SELECT action FROM decisions WHERE role = 'producer'")}
    assert actions == {"manifest_corrected", "filled_missing"}
    payload = json.loads(fq.calls[0][0][fq.calls[0][0].index("{"):])
    assert len(payload["scenes"]) == 5 and "qa_fixes" not in payload


def test_qa_fixes_passed_on_rework(env):
    store, blobs, job = env
    board = Storyboard.model_validate(storyboard_output())
    ctx = _ctx(store, blobs, job, board)
    put_json(ctx, "qa/report.json", QAReport(scores={}, passed=False, redo_from="producing_assets",
                                             fixes=["2번 장면 영상이 내용과 무관"]), "qa")
    store.transition(job.id, "queued", "researching", qa_rounds=1)
    fq = FakeQuery({"AssetManifest": result_message(manifest_output(job.id))})
    asyncio.run(producer.run(_ctx(store, blobs, job), RoleDeps(query_fn=fq, tts=MockTTS())))
    payload = json.loads(fq.calls[0][0][fq.calls[0][0].index("{"):])
    assert payload["qa_fixes"] == ["2번 장면 영상이 내용과 무관"]


def test_storyboard_change_refreshes_stale_assets(env):
    store, blobs, job = env
    board = Storyboard.model_validate(storyboard_output())
    stock = FakeStock()
    deps = RoleDeps(tts=MockTTS(), stock=stock)
    asyncio.run(producer.run(_ctx(store, blobs, job, board), deps, use_llm=False))
    first_audio = store.artifacts(job.id, "audio")[1].content_hash
    board.scenes[1].narration = "새로 쓴 두 번째 장면 내레이션입니다."
    board.scenes[1].query_or_prompt = "laundry basket"
    asyncio.run(producer.run(_ctx(store, blobs, job, board), deps, use_llm=False))
    assert store.artifacts(job.id, "audio")[1].content_hash != first_audio
    assert stock.queries.count("laundry basket") == 1
    assert len(stock.queries) == 5 + 1  # 검색어가 같은 장면은 저장된 클립을 다시 쓴다


def test_network_errors_fall_back_to_placeholder(env):
    store, blobs, job = env
    board = Storyboard.model_validate(storyboard_output())
    out = asyncio.run(producer.run(_ctx(store, blobs, job, board),
                                   RoleDeps(tts=MockTTS(), stock=FakeStock(fail={0, 1})), use_llm=False))
    assert [s.visual_key is None for s in out.output.scenes] == [True, True, False, False, False]


def test_role_failure_carries_tool_cost(env):
    store, blobs, job = env
    board = Storyboard.model_validate(storyboard_output())
    fq = FakeQuery({"AssetManifest": result_message(None, subtype="error_max_turns", is_error=True, cost=0.3)})
    with pytest.raises(RetryableError) as ei:
        asyncio.run(producer.run(_ctx(store, blobs, job, board), RoleDeps(query_fn=fq, tts=MockTTS())))
    assert ei.value.cost_usd == pytest.approx(0.3)
