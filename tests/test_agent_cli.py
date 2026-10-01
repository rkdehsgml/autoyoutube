"""CLI 종단 테스트 — 기본 mock 은 외부 호출 없이 진짜 mp4, --live 는 키가 있어야만."""
import subprocess
import sys
from pathlib import Path

from agent.adapters.store_sqlite import SqliteStore
from agent.cli import main
from agent.media.ffmpeg import video_size

ROOT = Path(__file__).resolve().parent.parent


def _paths(tmp_path):
    return ["--db", str(tmp_path / "agent.db"), "--media", str(tmp_path / "media")]


def test_local_mock_renders_real_video(tmp_path, capsys):
    rc = main(["local", "--mock", "--topic", "장마철 원룸 곰팡이", "--quiet", *_paths(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "awaiting_approval" in out
    job = SqliteStore(tmp_path / "agent.db").list_jobs()[0]
    assert job.state == "awaiting_approval"
    final = tmp_path / "media" / "jobs" / job.id / "final.mp4"
    assert video_size(final) == (1080, 1920)


def test_status_decide_and_resume(tmp_path, capsys):
    main(["local", "--fake-media", "--quiet", *_paths(tmp_path)])
    job_id = SqliteStore(tmp_path / "agent.db").list_jobs()[0].id
    capsys.readouterr()

    assert main(["status", *_paths(tmp_path)]) == 0
    assert job_id in capsys.readouterr().out
    assert main(["status", "--job-id", job_id, *_paths(tmp_path)]) == 0
    assert "packaging" in capsys.readouterr().out

    assert main(["decide", job_id, "redo", "--reason", "훅 약함", *_paths(tmp_path)]) == 0
    assert "storyboarding" in capsys.readouterr().out
    assert main(["local", "--fake-media", "--job-id", job_id, "--quiet", *_paths(tmp_path)]) == 0
    assert main(["decide", job_id, "approve", *_paths(tmp_path)]) == 0
    assert SqliteStore(tmp_path / "agent.db").get_job(job_id).state == "approved"
    assert main(["decide", job_id, "approve", *_paths(tmp_path)]) == 1  # 이미 승인됨


def test_qa_fail_flag_leads_to_needs_human(tmp_path):
    assert main(["local", "--fake-media", "--qa-fail", "3", "--quiet", *_paths(tmp_path)]) == 0
    assert SqliteStore(tmp_path / "agent.db").list_jobs()[0].state == "needs_human"


def test_live_requires_api_key(tmp_path, monkeypatch, capsys):
    for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    rc = main(["local", "--live", "--env-file", str(tmp_path / "none.env"), *_paths(tmp_path)])
    assert rc == 2 and "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "agent.db").exists()  # 아무것도 만들지 않음


def test_python_dash_m_entrypoint(tmp_path):
    r = subprocess.run([sys.executable, "-m", "agent", "local", "--fake-media", "--quiet", *_paths(tmp_path)],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "awaiting_approval" in r.stdout
