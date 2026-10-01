"""producer 도구·미디어 어댑터 테스트 (네트워크 없음, ffmpeg 사용)."""
import asyncio
import json
from pathlib import Path

import pytest
from fakes import storyboard_output

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.store_sqlite import SqliteStore
from agent.adapters.tts_google import GoogleTTS
from agent.adapters.tts_mock import MockTTS
from agent.adapters.visual_pexels import PexelsStock, pick_file
from agent.core.models import Storyboard, VisualResult
from agent.media.ffmpeg import ffmpeg
from agent.tools.base import ToolContext
from agent.tools.media import build_media_tools, check, load_words, stock, synthesize, words_key


def make_clip(path: Path, w: int = 720, h: int = 1280, sec: float = 1.0) -> Path:
    ffmpeg("-f", "lavfi", "-i", f"color=c=0x0f766e:s={w}x{h}:r=10:d={sec}", "-c:v", "libx264",
           "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path))
    return path


class FakeStock:
    name = "fakestock"
    kind = "stock"

    def __init__(self, w=720, h=1280, missing=(), fail=()):
        self.w, self.h, self.missing, self.fail = w, h, set(missing), set(fail)
        self.queries: list[str] = []

    def create(self, spec, out, exclude=None):
        self.queries.append(spec.query_or_prompt)
        if spec.scene in self.fail:
            raise ConnectionError("pexels down")
        if spec.scene in self.missing:
            return None
        make_clip(Path(out), self.w, self.h)
        return VisualResult(path=str(out), kind="stock", provider=self.name, cost_usd=0.0,
                            source_url=f"https://example.com/{spec.scene}")


class PaidTTS(MockTTS):
    name = "paid"
    cost_per_char = 0.001


@pytest.fixture
def tctx(tmp_path):
    store = SqliteStore(":memory:")
    blobs = LocalBlobStore(tmp_path / "media")
    job = store.create_job("manual")
    work = tmp_path / "work"
    work.mkdir()
    board = Storyboard.model_validate(storyboard_output())
    return ToolContext(job=job, store=store, blobs=blobs, workdir=work, storyboard=board, tts=MockTTS(),
                       voice="ko-KR-SunHiNeural", stock=FakeStock())


def run(coro):
    return asyncio.run(coro)


def test_synthesize_writes_audio_and_words_idempotently(tctx):
    first = run(synthesize(tctx, 0))
    assert first["audio_key"] == f"jobs/{tctx.job.id}/audio/scene_0.mp3" and not first["cached"]
    assert tctx.blobs.exists(words_key(first["audio_key"]))
    words = load_words(tctx, first["audio_key"], tctx.workdir)
    assert words and words[-1].end <= first["duration"] + 0.01
    art = tctx.store.artifacts(tctx.job.id, "audio")[0]
    assert art.provider == "mock" and art.checks["duration"] > 1
    again = run(synthesize(tctx, 0))
    assert again["cached"] and again["audio_key"] == first["audio_key"]


def test_synthesize_regenerates_when_narration_changes(tctx):
    run(synthesize(tctx, 1))
    tctx.storyboard.scenes[1].narration = "완전히 바뀐 내레이션 문장입니다."
    assert run(synthesize(tctx, 1))["cached"] is False


def test_synthesize_rejects_bad_scene_and_counts_cost(tctx):
    with pytest.raises(ValueError):
        run(synthesize(tctx, 7))
    tctx.tts = PaidTTS()
    run(synthesize(tctx, 0))
    assert tctx.cost_usd == pytest.approx(len(tctx.storyboard.scenes[0].narration) * 0.001)


def test_stock_saves_visual_and_check_passes(tctx):
    res = run(stock(tctx, 0, "dehumidifier room"))
    assert res["found"] and res["visual_key"] == f"jobs/{tctx.job.id}/visuals/scene_0.mp4"
    assert run(stock(tctx, 0, "dehumidifier room"))["cached"]
    assert tctx.stock.queries == ["dehumidifier room"]
    rep = run(check(tctx, res["visual_key"]))
    assert rep["ratio_ok"] and rep["resolution"] == "720x1280" and rep["issues"] == []
    assert tctx.store.artifacts(tctx.job.id, "visual")[0].checks["ratio_ok"] is True


def test_check_flags_landscape_and_low_res(tctx):
    tctx.stock = FakeStock(w=640, h=360)
    key = run(stock(tctx, 1, "window"))["visual_key"]
    rep = run(check(tctx, key))
    assert rep["ratio_ok"] is False and len(rep["issues"]) == 2


def test_check_only_this_job(tctx):
    with pytest.raises(ValueError):
        run(check(tctx, "jobs/OTHER/visuals/scene_0.mp4"))
    with pytest.raises(ValueError):
        run(check(tctx, f"jobs/{tctx.job.id}/visuals/none.mp4"))


def test_stock_without_provider_or_results(tctx):
    tctx.stock = None
    assert run(stock(tctx, 0, "x"))["found"] is False
    tctx.stock = FakeStock(missing={0})
    assert run(stock(tctx, 0, "x"))["found"] is False
    with pytest.raises(ValueError):
        run(stock(tctx, 0, "  "))


def test_tool_wrappers_return_errors_instead_of_raising(tctx):
    tools = {t.name: t for t in build_media_tools(tctx)}
    assert set(tools) == {"tts_synthesize", "stock_search", "check_asset"}
    ok = run(tools["tts_synthesize"].handler({"scene": 0}))
    assert "is_error" not in ok and json.loads(ok["content"][0]["text"])["audio_key"].endswith("scene_0.mp3")
    assert run(tools["tts_synthesize"].handler({"scene": 99}))["is_error"]
    tctx.stock = FakeStock(fail={2})
    bad = run(tools["stock_search"].handler({"scene": 2, "query": "rain"}))
    assert bad["is_error"] and "ConnectionError" in bad["content"][0]["text"]
    assert run(tools["check_asset"].handler({"key": "../../etc/passwd"}))["is_error"]


# ---------------------------------------------------------------- 어댑터


class FakeResp:
    def __init__(self, data=None, content=b""):
        self._data, self._content = data, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._data

    def iter_content(self, n):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, videos):
        self.videos = videos
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if "search" in url:
            return FakeResp({"videos": self.videos})
        return FakeResp(content=b"MP4DATA")


def test_pexels_picks_portrait_and_skips_used(tmp_path):
    videos = [
        {"id": 1, "url": "https://pexels.com/v/1",
         "video_files": [{"width": 1920, "height": 1080, "link": "https://x/1-land.mp4"}]},
        {"id": 2, "url": "https://pexels.com/v/2",
         "video_files": [{"width": 720, "height": 1280, "link": "https://x/2-720.mp4"},
                         {"width": 1080, "height": 1920, "link": "https://x/2-1080.mp4"}]},
        {"id": 3, "url": "https://pexels.com/v/3",
         "video_files": [{"width": 1080, "height": 1920, "link": "https://x/3.mp4"}]},
    ]
    assert pick_file(videos[1])["link"].endswith("1080.mp4")
    sess = FakeSession(videos)
    px = PexelsStock(api_key="test", session=sess)
    from agent.core.models import VisualSpec
    used: set = set()
    r1 = px.create(VisualSpec(scene=0, kind="stock", query_or_prompt="rain", target_sec=4), tmp_path / "a.mp4", used)
    r2 = px.create(VisualSpec(scene=1, kind="stock", query_or_prompt="rain", target_sec=4), tmp_path / "b.mp4", used)
    assert r1.source_url.endswith("/2") and r2.source_url.endswith("/3") and used == {2, 3}
    assert (tmp_path / "a.mp4").read_bytes() == b"MP4DATA"
    assert sess.calls[0][1]["params"]["orientation"] == "portrait"
    assert px.create(VisualSpec(scene=2, kind="stock", query_or_prompt="rain", target_sec=4),
                     tmp_path / "c.mp4", used) is None


def test_keys_required(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        PexelsStock()
    with pytest.raises(RuntimeError):
        GoogleTTS(voice="ko-KR-Chirp3-HD-Aoede")
