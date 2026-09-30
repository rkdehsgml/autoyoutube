"""CLI 종단 테스트 — `agent local --mock` 이 queued → awaiting_approval 까지 간다 (1단계 완료 기준)."""
import subprocess
import sys
from pathlib import Path

from agent.adapters.store_sqlite import SqliteStore
from agent.cli import main

ROOT = Path(__file__).resolve().parent.parent


def _paths(tmp_path):
    return ["--db", str(tmp_path / "agent.db"), "--media", str(tmp_path / "media")]


def test_local_mock_reaches_awaiting_approval(tmp_path, capsys):
    rc = main(["local", "--mock", "--topic", "장마철 원룸 곰팡이", "--quiet", *_paths(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "awaiting_approval" in out
    job = SqliteStore(tmp_path / "agent.db").list_jobs()[0]
    assert job.state == "awaiting_approval"
    assert (tmp_path / "media" / "jobs" / job.id / "final.mp4").exists()


def test_status_decide_and_resume(tmp_path, capsys):
    main(["local", "--quiet", *_paths(tmp_path)])
    job_id = SqliteStore(tmp_path / "agent.db").list_jobs()[0].id
    capsys.readouterr()

    assert main(["status", *_paths(tmp_path)]) == 0
    assert job_id in capsys.readouterr().out
    assert main(["status", "--job-id", job_id, *_paths(tmp_path)]) == 0
    assert "packaging" in capsys.readouterr().out

    assert main(["decide", job_id, "redo", "--reason", "훅 약함", *_paths(tmp_path)]) == 0
    assert "storyboarding" in capsys.readouterr().out
    assert main(["local", "--job-id", job_id, "--quiet", *_paths(tmp_path)]) == 0
    assert main(["decide", job_id, "approve", *_paths(tmp_path)]) == 0
    assert SqliteStore(tmp_path / "agent.db").get_job(job_id).state == "approved"
    assert main(["decide", job_id, "approve", *_paths(tmp_path)]) == 1  # 이미 승인됨


def test_qa_fail_flag_leads_to_needs_human(tmp_path):
    assert main(["local", "--qa-fail", "3", "--quiet", *_paths(tmp_path)]) == 0
    assert SqliteStore(tmp_path / "agent.db").list_jobs()[0].state == "needs_human"


def test_live_is_not_available_yet(tmp_path):
    assert main(["local", "--live", *_paths(tmp_path)]) == 2
    assert not (tmp_path / "agent.db").exists()


def test_python_dash_m_entrypoint(tmp_path):
    r = subprocess.run([sys.executable, "-m", "agent", "local", "--mock", "--quiet", *_paths(tmp_path)],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "awaiting_approval" in r.stdout
