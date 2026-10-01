"""editor(렌더)·packaging·임시 critic — v0 렌더 테스트와 같은 기준으로 확인한다."""
import asyncio
import copy

import pytest
from fakes import storyboard_output
from test_agent_media_tools import FakeStock

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.store_sqlite import SqliteStore
from agent.adapters.tts_mock import MockTTS
from agent.core.channel import load_channel
from agent.core.models import QAReport, Storyboard
from agent.core.ports import StepContext
from agent.media.ffmpeg import media_duration, video_size
from agent.roles import critic_stub, editor, packaging, producer
from agent.roles.deps import RoleDeps, put_json


@pytest.fixture
def produced(tmp_path):
    store = SqliteStore(":memory:")
    blobs = LocalBlobStore(tmp_path / "media")
    job = store.create_job("manual")
    board = Storyboard.model_validate(storyboard_output())
    deps = RoleDeps(tts=MockTTS(), stock=FakeStock(missing={1, 3}))
    ctx = StepContext(job=job, store=store, blobs=blobs, step="producing_assets")
    put_json(ctx, "storyboard.json", board, "storyboard")
    manifest = asyncio.run(producer.run(ctx, deps, use_llm=False)).output
    return store, blobs, job, board, manifest, deps


def test_editor_renders_vertical_video_with_subtitles(produced):
    store, blobs, job, board, manifest, deps = produced
    ctx = StepContext(job=store.get_job(job.id), store=store, blobs=blobs, step="rendering")
    out = asyncio.run(editor.run(ctx, deps)).output
    final = blobs.local_path(out.final_key)
    assert video_size(final) == (1080, 1920)
    audio_total = sum(s.duration_sec for s in manifest.scenes)
    assert audio_total < out.duration_sec < audio_total + 0.3 * len(manifest.scenes) + 0.5
    assert media_duration(final) == pytest.approx(out.duration_sec, abs=0.05)
    assert video_size(blobs.local_path(out.thumb_key)) == (1080, 1920)
    subs = blobs.local_path(f"jobs/{job.id}/subs.ass").read_text(encoding="utf-8")
    assert subs.count(",Sub,") > len(board.scenes)        # 장면마다 자막 덩어리
    assert subs.count(",Hook,") == 1 and subs.count(",Label,") == 1  # 훅 + 장면 0 라벨
    kinds = {a.kind for a in store.artifacts(job.id)}
    assert {"final", "thumb", "subs", "manifest", "audio", "visual"} <= kinds


def test_packaging_without_affiliate(produced):
    store, blobs, job, board, manifest, deps = produced
    ctx = StepContext(job=store.get_job(job.id), store=store, blobs=blobs, step="packaging")
    meta = asyncio.run(packaging.run(ctx, deps)).output
    assert meta.affiliate is False and meta.contains_synthetic_media is False
    assert "쿠팡 파트너스" not in meta.youtube.description
    assert meta.youtube.description.startswith(board.description)
    assert "고르는 기준: 소비전력보다 사용 시간을 먼저 본다" in meta.youtube.description
    assert meta.youtube.tags == ["자취", "제습기", "생활꿀팁"]
    assert "#광고" not in meta.instagram.caption
    assert store.artifacts(job.id, "meta")[0].r2_key == f"jobs/{job.id}/meta.json"


def test_packaging_with_affiliate_puts_disclosure_first():
    channel = copy.deepcopy(load_channel())
    channel["disclosure"]["enable_affiliate"] = True
    board = Storyboard.model_validate(storyboard_output())
    meta = packaging.build_meta(channel, board, used_ai=True)
    assert meta.affiliate and meta.contains_synthetic_media
    assert meta.youtube.description.startswith("이 포스팅은 쿠팡 파트너스")
    assert meta.instagram.caption.startswith("이 포스팅은 쿠팡 파트너스")
    assert "#광고" in meta.instagram.caption and "- 저소음 제습기: 원룸은 소음 우선" in meta.youtube.description
    no_products = board.model_copy(update={"products": []})
    assert packaging.build_meta(channel, no_products).affiliate is False  # 상품 없으면 문구 없음


def test_normalize_tags():
    assert packaging.normalize_tags(["자취", "#자취", "# 생활 꿀팁", "#", "a", "b", "c", "d"]) == \
        ["#자취", "#생활꿀팁", "#a", "#b", "#c"]


def test_critic_passthrough(produced):
    store, blobs, job, *_ = produced
    ctx = StepContext(job=store.get_job(job.id), store=store, blobs=blobs, step="reviewing")
    out = asyncio.run(critic_stub.run(ctx, RoleDeps()))
    assert isinstance(out.output, QAReport) and out.output.passed and out.output.scores == {}
