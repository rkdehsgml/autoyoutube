"""live 모드 종단 — 실제 역할 코드 경로를 가짜 query·MockTTS 로 끝까지 돌린다 (네트워크 없음)."""
import asyncio

from fakes import FakeQuery, manifest_output, research_output, storyboard_output

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.notify_memory import MemoryNotifier
from agent.adapters.store_sqlite import SqliteStore
from agent.adapters.tts_mock import MockTTS
from agent.core.channel import load_channel
from agent.core.settings import PUBLISH_TOOLS
from agent.media.ffmpeg import video_size
from agent.orchestrator import STEPS, Orchestrator
from agent.roles.deps import RoleDeps
from agent.roles.registry import build_handlers, deps_for


def test_live_path_end_to_end(tmp_path):
    store = SqliteStore(":memory:")
    blobs = LocalBlobStore(tmp_path / "media")
    notifier = MemoryNotifier()
    job = store.create_job("telegram", requested_topic="제습기 전기세 오해")
    fq = FakeQuery({
        "ResearchResult": research_output(chosen=0, requested="제습기 전기세 오해"),
        "Storyboard": storyboard_output(),
        "AssetManifest": lambda prompt, options: manifest_output(job.id),
    })
    deps = RoleDeps(channel=load_channel(), query_fn=fq, tts=MockTTS(), stock=None)
    orch = Orchestrator(store, blobs, build_handlers("live", deps), notifier=notifier)
    job = asyncio.run(orch.advance(job.id, "run-live"))

    assert job.state == "awaiting_approval", job.error
    assert fq.titles() == ["ResearchResult", "Storyboard", "AssetManifest"]
    for _, opts in fq.calls:
        assert opts.permission_mode == "dontAsk" and not PUBLISH_TOOLS & set(opts.allowed_tools)
    final = blobs.local_path(store.artifacts(job.id, "final")[0].r2_key)
    assert video_size(final) == (1080, 1920)
    assert job.cost_usd == 0.03  # 역할 3개 × $0.01 (MockTTS·단색 배경은 무료)
    assert [r.status for r in store.step_runs(job.id)] == ["ok"] * len(STEPS)
    assert notifier.previews and notifier.previews[0][2].startswith("제습기 전기세")


def test_mock_mode_deps_never_call_out():
    deps = deps_for("mock")
    assert isinstance(deps.tts, MockTTS) and deps.stock is None and deps.query_fn is None


def test_live_deps_without_pexels_key_warns(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    warnings = []
    deps = deps_for("live", warn=warnings.append)
    assert deps.stock is None and warnings and type(deps.tts).__name__ == "EdgeTTS"
