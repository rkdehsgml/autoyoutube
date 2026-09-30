"""스키마·모델·전이표 단위 테스트."""
import sqlite3

import pytest
from pydantic import ValidationError

from agent.adapters.store_sqlite import SCHEMA_PATH
from agent.core import models
from agent.core.clock import new_ulid
from agent.core.states import (
    ALLOWED, FORWARD, JOB_STATES, TERMINAL, InvalidTransition, check_transition, is_allowed,
)

TABLES = {
    "settings", "topics", "jobs", "step_runs", "artifacts", "evals", "decisions",
    "approvals", "publications", "metrics", "config_versions", "events",
}
ROW_MODELS = {
    "settings": models.Setting, "topics": models.Topic, "jobs": models.Job, "step_runs": models.StepRun,
    "artifacts": models.Artifact, "evals": models.EvalRow, "decisions": models.Decision,
    "approvals": models.Approval, "publications": models.Publication, "metrics": models.MetricRow,
    "config_versions": models.ConfigVersion, "events": models.Event,
}


def _schema_columns() -> dict[str, list[str]]:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {n: [c[1] for c in conn.execute(f"PRAGMA table_info({n})")] for n in names if n != "sqlite_sequence"}


def test_schema_has_12_tables():
    assert set(_schema_columns()) == TABLES


@pytest.mark.parametrize("table", sorted(TABLES))
def test_row_models_match_schema_columns(table):
    cols = _schema_columns()[table]
    assert set(ROW_MODELS[table].model_fields) == set(cols)


def test_16_states_and_forward_chain():
    assert len(JOB_STATES) == 16
    for a, b in zip(FORWARD, FORWARD[1:]):
        assert is_allowed(a, b)


@pytest.mark.parametrize("frm,to", [
    ("queued", "rendering"),        # 건너뛰기
    ("rendering", "storyboarding"),  # QA가 아닌 되돌리기
    ("done", "queued"),              # 종료 상태에서 나가기
    ("failed", "queued"),
    ("approved", "storyboarding"),
    ("awaiting_approval", "publishing"),
])
def test_invalid_transitions(frm, to):
    assert not is_allowed(frm, to)
    with pytest.raises(InvalidTransition):
        check_transition(frm, to)


def test_backward_transitions_are_only_qa_and_redo_button():
    order = {s: i for i, s in enumerate(FORWARD)}
    backward = {(a, b) for a, b in ALLOWED if a in order and b in order and order[b] < order[a]}
    assert backward == {
        ("reviewing", "storyboarding"), ("reviewing", "producing_assets"), ("reviewing", "rendering"),
        ("awaiting_approval", "storyboarding"),
    }
    assert ("needs_human", "storyboarding") in ALLOWED


def test_terminal_states_have_no_exit():
    assert not [t for t in ALLOWED if t[0] in TERMINAL]


def test_unknown_state_rejected():
    with pytest.raises(InvalidTransition):
        check_transition("queued", "exploded")


def _scene(i=0, **kw):
    d = dict(narration=f"장면 {i}", visual="stock", query_or_prompt="rain window", target_sec=5)
    d.update(kw)
    return d


def test_storyboard_validation():
    ok = models.Storyboard(title="장마철 곰팡이", hook="냄새 원인은?", scenes=[_scene(i) for i in range(4)],
                           insight="환기보다 제습이 먼저", hashtags=["#자취"])
    assert len(ok.scenes) == 4
    with pytest.raises(ValidationError):  # 장면 3개
        models.Storyboard(title="t", hook="h", scenes=[_scene(i) for i in range(3)], insight="i", hashtags=[])
    with pytest.raises(ValidationError):  # 훅 15자 초과
        models.Storyboard(title="t", hook="가" * 16, scenes=[_scene(i) for i in range(4)], insight="i", hashtags=[])
    with pytest.raises(ValidationError):  # 장면 길이 범위
        models.Scene(**_scene(target_sec=1))


def test_qa_report_redo_from_literal():
    models.QAReport(scores={"hook": 0.8}, passed=False, redo_from="rendering", fixes=["자막 겹침"])
    with pytest.raises(ValidationError):
        models.QAReport(scores={}, passed=False, redo_from="packaging")


def test_ulid_format_and_order():
    a, b = new_ulid(), new_ulid()
    assert len(a) == 26 and a.isalnum()
    assert a != b
