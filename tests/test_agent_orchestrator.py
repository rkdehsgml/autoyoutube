"""상태 머신 테스트 — 가짜 역할로 전이·재시도·QA 루프·비용 상한·lease·사람 판단을 확인한다."""
import asyncio

import pytest

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.notify_memory import MemoryNotifier
from agent.adapters.store_sqlite import SqliteStore
from agent.core.clock import FakeClock
from agent.core.settings import PUBLISH_TOOLS, load_roles
from agent.orchestrator import MAX_HUMAN_REDO, STEPS, Orchestrator, apply_decision
from agent.roles.mock import MockRoles


@pytest.fixture
def env(tmp_path):
    clock = FakeClock()
    store = SqliteStore(":memory:", clock=clock)
    blobs = LocalBlobStore(tmp_path / "media")
    notifier = MemoryNotifier()
    return store, blobs, notifier, clock


def _run(env, roles: MockRoles | None = None, topic="장마철 원룸 곰팡이 냄새", owner="run-1", job=None):
    store, blobs, notifier, _ = env
    roles = roles or MockRoles()
    orch = Orchestrator(store, blobs, roles.handlers(), notifier=notifier)
    job = job or store.create_job("manual", requested_topic=topic)
    return asyncio.run(orch.advance(job.id, owner)), roles


def test_steps_table_covers_produce_states():
    assert list(STEPS) == ["queued", "researching", "storyboarding", "producing_assets", "rendering",
                           "reviewing", "packaging"]
    assert STEPS["packaging"].to == "awaiting_approval"


def test_mock_end_to_end_reaches_awaiting_approval(env):
    store, blobs, notifier, _ = env
    job, _ = _run(env)
    assert job.state == "awaiting_approval"
    assert job.lease_owner is None and job.attempt == 0 and job.qa_rounds == 0
    assert job.topic_id and job.format_id
    kinds = {a.kind for a in store.artifacts(job.id)}
    assert kinds == {"research", "storyboard", "audio", "visual", "subs", "final", "thumb", "qa", "meta"}
    for a in store.artifacts(job.id):
        assert a.r2_key.startswith(f"jobs/{job.id}/") and blobs.exists(a.r2_key)
    runs = store.step_runs(job.id)
    assert [r.step for r in runs] == list(STEPS)
    assert all(r.status == "ok" for r in runs)
    assert job.cost_usd == pytest.approx(0.095)
    assert len(notifier.previews) == 1 and notifier.previews[0][0] == job.id
    assert len(store.query("SELECT * FROM evals WHERE job_id = ?", [job.id])) == 7


def test_qa_redo_once_then_pass(env):
    store, *_ = env
    job, roles = _run(env, MockRoles(qa_failures=1, redo_from="producing_assets"))
    assert job.state == "awaiting_approval"
    assert job.qa_rounds == 1
    assert roles.calls["producer"] == 2 and roles.calls["writer"] == 1
    steps = [r.step for r in store.step_runs(job.id)]
    assert steps.count("reviewing") == 2
    assert store.query("SELECT action FROM decisions WHERE role = 'critic'")[0]["action"] == \
        "redo_from=producing_assets"


def test_qa_third_failure_goes_to_needs_human(env):
    store, _, notifier, _ = env
    job, roles = _run(env, MockRoles(qa_failures=5, redo_from="rendering"))
    assert job.state == "needs_human"
    assert job.qa_rounds == 2
    assert roles.calls["critic"] == 3 and roles.calls["render_video"] == 3
    assert any("사람 확인 필요" in m for m in notifier.messages)
    assert job.lease_owner is None


def test_qa_fail_without_redo_from_goes_to_needs_human(env):
    job, roles = _run(env, MockRoles(qa_failures=1, redo_from=None))
    assert job.state == "needs_human" and job.qa_rounds == 0
    assert roles.calls["critic"] == 1


def test_transient_error_retries_then_succeeds(env):
    store, *_ = env
    job, roles = _run(env, MockRoles(transient={"writer": 2}))
    assert job.state == "awaiting_approval"
    assert roles.calls["writer"] == 3 and job.attempt == 0
    failed = [r for r in store.step_runs(job.id) if r.status == "failed"]
    assert len(failed) == 2 and all(r.step == "storyboarding" for r in failed)


def test_transient_error_three_times_fails(env):
    _, _, notifier, _ = env
    job, roles = _run(env, MockRoles(transient={"producer": 3}))
    assert job.state == "failed"
    assert "3회 재시도 실패" in job.error
    assert roles.calls["producer"] == 3
    assert any(m.startswith("실패:") for m in notifier.messages)


def test_unexpected_error_fails_without_retry(env):
    job, roles = _run(env, MockRoles(crash="critic"))
    assert job.state == "failed" and "RuntimeError" in job.error
    assert roles.calls["critic"] == 1


def test_invalid_role_output_is_retried(env):
    store, blobs, notifier, _ = env
    roles = MockRoles()
    handlers = roles.handlers()
    calls = {"n": 0}
    good_writer = handlers["writer"]

    async def flaky_writer(ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            from agent.core.models import Storyboard
            Storyboard.model_validate({"title": "x", "hook": "h", "scenes": [], "insight": "", "hashtags": []})
        return await good_writer(ctx)

    handlers["writer"] = flaky_writer
    orch = Orchestrator(store, blobs, handlers, notifier=notifier)
    job = store.create_job("manual", requested_topic="빨래 쉰내")
    job = asyncio.run(orch.advance(job.id, "run-1"))
    assert job.state == "awaiting_approval" and calls["n"] == 2


def test_job_budget_enforced(env):
    job, roles = _run(env, MockRoles(costs={"writer": 0.09, "producer": 0.95}))
    assert job.state == "failed"
    assert "job 비용 상한" in job.error
    assert "render_video" not in roles.calls
    assert job.cost_usd == pytest.approx(1.05)  # 쓴 비용은 기록된다


def test_role_budget_enforced(env):
    job, roles = _run(env, MockRoles(costs={"writer": 0.5}))  # writer 상한 $0.10
    assert job.state == "failed" and "writer 역할 비용 상한" in job.error
    assert "producer" not in roles.calls


def test_job_budget_setting_from_store(env):
    store, *_ = env
    store.set_setting("job_budget_usd", "0.02")
    job, _ = _run(env)
    assert job.state == "failed" and "job 비용 상한" in job.error


def test_monthly_budget_checked_at_start(env):
    store, *_ = env
    store.set_setting("monthly_budget_usd", "0.5")
    old = store.create_job("manual")
    store.record_run(old.id, "writer", 0.6, {})
    job, roles = _run(env)
    assert job.state == "failed" and "월 비용 상한" in job.error
    assert not roles.calls


def test_lease_held_by_other_run_is_noop(env):
    store, *_ = env
    job = store.create_job("manual", requested_topic="외풍")
    assert store.acquire_lease(job.id, "other-run", 1800)
    job2, roles = _run(env, job=job)
    assert job2.state == "queued" and not roles.calls
    assert store.get_job(job.id).lease_owner == "other-run"


def test_paused_does_not_start_new_jobs(env):
    store, *_ = env
    store.set_setting("paused", "true")
    job, roles = _run(env)
    assert job.state == "queued" and not roles.calls


def test_lost_lease_stops_without_transition(env):
    store, blobs, notifier, clock = env
    roles = MockRoles()
    handlers = roles.handlers()
    good_producer = handlers["producer"]

    async def slow_producer(ctx):
        out = await good_producer(ctx)
        clock.advance(1801)  # lease 만료
        assert ctx.store.acquire_lease(ctx.job.id, "run-2", 1800)  # 워치독이 재디스패치한 실행이 가져감
        return out

    handlers["producer"] = slow_producer
    orch = Orchestrator(store, blobs, handlers, notifier=notifier)
    job = store.create_job("manual", requested_topic="외풍")
    job = asyncio.run(orch.advance(job.id, "run-1"))
    assert job.state == "producing_assets"  # run-1 은 전이하지 못했다
    assert job.lease_owner == "run-2"       # 남의 lease를 반납하지도 않았다
    assert store.query("SELECT kind FROM events")[0]["kind"] == "transition_lost"


def test_resume_after_crash_continues_from_current_state(env):
    store, blobs, notifier, clock = env
    job, _ = _run(env, MockRoles(crash="producer"))
    assert job.state == "failed"
    # 새 job은 영향 없이 처음부터 끝까지 간다
    job2, _ = _run(env, owner="run-2")
    assert job2.state == "awaiting_approval"


def test_handler_must_return_step_output(env):
    store, blobs, notifier, _ = env
    handlers = MockRoles().handlers()

    async def bad(ctx):
        return {"not": "a StepOutput"}

    handlers["publisher"] = bad
    orch = Orchestrator(store, blobs, handlers, notifier=notifier)
    job = store.create_job("manual")
    assert asyncio.run(orch.advance(job.id, "r")).state == "failed"


def test_missing_handler_rejected(env):
    store, blobs, *_ = env
    handlers = MockRoles().handlers()
    del handlers["critic"]
    with pytest.raises(ValueError):
        Orchestrator(store, blobs, handlers)


# ---------------------------------------------------------------- 사람 판단


def test_approve_and_reject(env):
    store, *_ = env
    job, _ = _run(env)
    job = apply_decision(store, job.id, "approved")
    assert job.state == "approved" and store.approval(job.id).decision == "approved"
    job2, _ = _run(env, topic="외풍")
    assert apply_decision(store, job2.id, "rejected", "주제 별로").state == "rejected"
    with pytest.raises(ValueError):
        apply_decision(store, job2.id, "approved")  # 이미 끝난 job


def test_redo_button_goes_back_to_storyboarding_and_reruns(env):
    store, blobs, notifier, _ = env
    roles = MockRoles()
    job, _ = _run(env, roles)
    job = apply_decision(store, job.id, "redo", "훅이 약함")
    assert job.state == "storyboarding" and job.qa_rounds == 0
    orch = Orchestrator(store, blobs, roles.handlers(), notifier=notifier)
    job = asyncio.run(orch.advance(job.id, "run-2"))
    assert job.state == "awaiting_approval"
    assert roles.calls["writer"] == 2 and roles.calls["researcher"] == 1
    assert len(notifier.previews) == 2


def test_redo_limit_and_needs_human_approve(env):
    store, blobs, notifier, _ = env
    roles = MockRoles()
    orch = Orchestrator(store, blobs, roles.handlers(), notifier=notifier)
    job, _ = _run(env, roles)
    for i in range(MAX_HUMAN_REDO):
        apply_decision(store, job.id, "redo")
        job = asyncio.run(orch.advance(job.id, f"run-{i + 2}"))
        assert job.state == "awaiting_approval"
    with pytest.raises(ValueError):
        apply_decision(store, job.id, "redo")
    # needs_human 에서 [그대로 승인]
    job3, _ = _run(env, MockRoles(qa_failures=1, redo_from=None), topic="보일러")
    assert apply_decision(store, job3.id, "approved").state == "approved"


def test_decision_requires_waiting_state(env):
    store, *_ = env
    job = store.create_job("manual")
    with pytest.raises(ValueError):
        apply_decision(store, job.id, "approved")
    with pytest.raises(ValueError):
        apply_decision(store, job.id, "maybe")


# ---------------------------------------------------------------- 역할 설정


def test_roles_config_loaded_without_publish_tools():
    roles = load_roles()
    assert set(roles) == {"researcher", "writer", "producer", "critic", "publisher", "analyst"}
    for cfg in roles.values():
        assert not PUBLISH_TOOLS & set(cfg.tools)
        assert cfg.model and cfg.max_turns > 0 and cfg.max_budget_usd > 0
    assert set(roles["publisher"].gated_tools) == PUBLISH_TOOLS


def test_roles_config_rejects_publish_tool_in_allowed(tmp_path):
    bad = tmp_path / "roles.yaml"
    bad.write_text("roles:\n  publisher:\n    model: m\n    max_turns: 1\n    max_budget_usd: 0.1\n"
                   "    tools: [publish_youtube]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_roles(bad)
