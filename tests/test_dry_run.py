"""API 키 없이 전체 파이프라인을 돌려 9:16 영상이 나오는지 확인한다.

  python -m pytest -q
"""
from pathlib import Path

from autotube import pipeline
from autotube.config import load_config
from autotube.utils import media_duration, video_size


def _cfg(affiliate: bool = False):
    cfg = load_config()
    cfg.set_path("providers.llm", "mock")
    cfg.set_path("providers.tts", "mock")
    cfg.set_path("providers.visuals", "placeholder")
    cfg.set_path("disclosure.enable_affiliate", affiliate)
    return cfg


def test_generate_mock(tmp_path: Path):
    job = pipeline.generate(_cfg(), topic="장마철 원룸 곰팡이", outputs_dir=tmp_path)
    assert job.video_path.exists()
    assert video_size(job.video_path) == (1080, 1920)
    assert 5 < media_duration(job.video_path) < 90
    meta = job.read_json("metadata.json")
    assert meta["affiliate"] is False
    assert "쿠팡 파트너스" not in meta["youtube"]["description"]
    assert (job.dir / "subs.ass").read_text(encoding="utf-8").count("Dialogue:") > 3


def test_affiliate_disclosure_first_line(tmp_path: Path):
    job = pipeline.generate(_cfg(affiliate=True), topic="자취방 외풍", outputs_dir=tmp_path)
    meta = job.read_json("metadata.json")
    assert meta["youtube"]["description"].startswith("이 포스팅은 쿠팡 파트너스")
    assert "#광고" in meta["instagram"]["caption"]
