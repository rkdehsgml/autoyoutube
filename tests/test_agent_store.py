"""SqliteStore 계약 테스트 — 같은 0001_init.sql 위에서 lease·조건부 전이·기록을 확인한다."""
import threading

import pytest

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.store_sqlite import SqliteStore
from agent.core.clock import FakeClock
from agent.core.models import Approval, Artifact, Publication, StepRun, Topic
from agent.core.ports import BlobStore, Store
from agent.core.states import InvalidTransition


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    return SqliteStore(":memory:", clock=clock)


def test_implements_protocols(store, tmp_path):
    assert isinstance(store, Store)
    assert isinstance(LocalBlobStore(tmp_path), BlobStore)


def test_create_and_get_job(store):
    job = store.create_job("manual", requested_topic="장마철 곰팡이")
    got = store.get_job(job.id)
    assert got.state == "queued" and got.requested_topic == "장마철 곰팡이"
    assert [j.id for j in store.list_jobs()] == [job.id]
    with pytest.raises(KeyError):
        store.get_job("nope")


def test_reopen_file_db_keeps_data(tmp_path):
    db = tmp_path / "a.db"
    job = SqliteStore(db).create_job("manual")
    assert SqliteStore(db).get_job(job.id).id == job.id  # 두 번째 열 때 DDL을 다시 돌리지 않음


# ---------------------------------------------------------------- lease


def test_lease_exclusive_until_expiry(store, clock):
    job = store.create_job("manual")
    assert store.acquire_lease(job.id, "run-1", ttl_sec=1800)
    assert not store.acquire_lease(job.id, "run-2", ttl_sec=1800)
    assert store.acquire_lease(job.id, "run-1", ttl_sec=1800)  # 같은 owner는 연장
    clock.advance(1801)
    assert store.acquire_lease(job.id, "run-2", ttl_sec=1800)  # 만료 후 인수
    assert store.get_job(job.id).lease_owner == "run-2"


def test_release_only_by_owner(store):
    job = store.create_job("manual")
    store.acquire_lease(job.id, "run-1", 1800)
    store.release_lease(job.id, "run-2")
    assert store.get_job(job.id).lease_owner == "run-1"
    store.release_lease(job.id, "run-1")
    assert store.get_job(job.id).lease_owner is None


def test_concurrent_lease_only_one_wins(tmp_path):
    db = tmp_path / "race.db"
    job = SqliteStore(db).create_job("manual")
    n = 16
    barrier = threading.Barrier(n)
    wins: list[str] = []
    errors: list[BaseException] = []

    def worker(i: int):
        try:
            s = SqliteStore(db)  # 스레드마다 별도 연결 (러너가 여러 개인 상황)
            barrier.wait()
            if s.acquire_lease(job.id, f"run-{i}", 1800):
                wins.append(f"run-{i}")
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(wins) == 1
    assert SqliteStore(db).get_job(job.id).lease_owner == wins[0]


# ---------------------------------------------------------------- 조건부 전이


def test_transition_conditional_on_state(store):
    job = store.create_job("manual")
    assert store.transition(job.id, "queued", "researching")
    assert not store.transition(job.id, "queued", "researching")  # 이미 바뀜 → 0행
    assert store.get_job(job.id).state == "researching"


def test_transition_rejects_invalid_edge(store):
    job = store.create_job("manual")
    with pytest.raises(InvalidTransition):
        store.transition(job.id, "queued", "rendering")


def test_transition_requires_valid_lease_when_owner_given(store, clock):
    job = store.create_job("manual")
    store.acquire_lease(job.id, "run-1", 60)
    assert not store.transition(job.id, "queued", "researching", owner="run-2")
    clock.advance(61)
    assert not store.transition(job.id, "queued", "researching", owner="run-1")  # 만료
    store.acquire_lease(job.id, "run-1", 60)
    assert store.transition(job.id, "queued", "researching", owner="run-1", attempt=0)


def test_transition_fields_whitelist(store):
    job = store.create_job("manual")
    with pytest.raises(ValueError):
        store.transition(job.id, "queued", "researching", state="done")
    with pytest.raises(ValueError):
        store.transition(job.id, "queued", "researching", **{"id; DROP TABLE jobs": 1})
    assert store.transition(job.id, "queued", "researching", format_id="myth_fact")
    assert store.get_job(job.id).format_id == "myth_fact"


def test_bump_attempt_and_cost(store):
    job = store.create_job("manual")
    store.bump_attempt(job.id)
    store.record_run(job.id, "writer", 0.12, {"tokens_in": 10})
    store.record_run(job.id, "critic", 0.03, {})
    j = store.get_job(job.id)
    assert j.attempt == 1 and j.cost_usd == pytest.approx(0.15)


# ---------------------------------------------------------------- 기록


def test_artifacts_step_runs_evals(store):
    job = store.create_job("manual")
    store.put_artifact(Artifact(job_id=job.id, kind="audio", scene=0, r2_key="jobs/x/audio/scene_0.mp3",
                                checks={"ok": True}))
    store.put_artifact(Artifact(job_id=job.id, kind="audio", scene=0, r2_key="jobs/x/audio/scene_0.mp3",
                                provider="mock"))  # 같은 PK → 교체
    store.put_artifact(Artifact(job_id=job.id, kind="final", r2_key="jobs/x/final.mp4"))
    assert len(store.artifacts(job.id)) == 2
    assert store.artifacts(job.id, "audio")[0].provider == "mock"

    rid = store.record_step(StepRun(job_id=job.id, step="researching", role="researcher", status="started"))
    store.record_step(StepRun(id=rid, job_id=job.id, step="researching", status="ok", cost_usd=0.01))
    runs = store.step_runs(job.id)
    assert len(runs) == 1 and runs[0].status == "ok" and runs[0].ended_at

    store.add_evals(job.id, "v1", {"hook": 0.9, "policy": 1.0}, "llm")
    assert len(store.query("SELECT * FROM evals WHERE job_id = ?", [job.id])) == 2


def test_topic_dedup(store):
    t1 = store.add_topic(Topic(id="T1", title="곰팡이", norm_hash="h1", source="manual"))
    t2 = store.add_topic(Topic(id="T2", title="곰팡이!", norm_hash="h1", source="web"))
    assert t1.id == t2.id == "T1"


def test_publication_pk_prevents_duplicates(store):
    job = store.create_job("manual")
    store.upsert_publication(Publication(job_id=job.id, platform="youtube", status="pending"))
    store.upsert_publication(Publication(job_id=job.id, platform="youtube", status="ok", post_id="abc"))
    rows = store.query("SELECT * FROM publications")
    assert len(rows) == 1 and rows[0]["post_id"] == "abc"


def test_approval_and_settings(store):
    job = store.create_job("manual")
    assert store.approval(job.id) is None
    store.put_approval(Approval(job_id=job.id, decision="approved"))
    assert store.approval(job.id).decision == "approved"
    assert store.get_setting("job_budget_usd", "1.0") == "1.0"
    store.set_setting("job_budget_usd", "0.5")
    store.set_setting("job_budget_usd", "0.7")
    assert store.get_setting("job_budget_usd") == "0.7"


def test_month_cost_only_this_month(store, clock):
    old = store.create_job("manual")
    store.record_run(old.id, "writer", 5.0, {})
    clock.advance(40 * 86400)  # 다음 달로
    new = store.create_job("manual")
    store.record_run(new.id, "writer", 0.3, {})
    assert store.month_cost() == pytest.approx(0.3)


def test_query_is_read_only(store):
    with pytest.raises(ValueError):
        store.query("DELETE FROM jobs")
    with pytest.raises(Exception):
        store.query("WITH x AS (SELECT 1) DELETE FROM jobs")
    store.create_job("manual")  # 읽기 전용 모드가 풀렸는지
    assert store.query("SELECT COUNT(*) AS n FROM jobs")[0]["n"] == 1


def test_local_blob_store(tmp_path):
    blobs = LocalBlobStore(tmp_path / "media")
    key = blobs.put("jobs/j1/research.json", b"{}", "application/json")
    assert blobs.exists(key)
    src = tmp_path / "a.txt"
    src.write_text("hi")
    blobs.put("jobs/j1/subs.ass", src, "text/plain")
    out = blobs.get("jobs/j1/subs.ass", tmp_path / "out" / "s.ass")
    assert out.read_text() == "hi"
    assert blobs.presigned_get(key).startswith("file://")
    for bad in ("../x", "/etc/passwd", ""):
        with pytest.raises(ValueError):
            blobs.put(bad, b"", "text/plain")
