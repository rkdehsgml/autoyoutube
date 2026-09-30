"""SqliteStore — 로컬·테스트용 Store. D1과 같은 DDL(worker/migrations/0001_init.sql)을 쓴다.

모든 상태 변경은 단일 조건부 UPDATE 한 문장이라 D1 REST에서도 그대로 원자적이다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent.core.clock import SystemClock, db_time, new_ulid
from agent.core.models import Approval, Artifact, Job, Publication, StepRun, Topic
from agent.core.ports import Clock
from agent.core.states import check_transition

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "worker" / "migrations" / "0001_init.sql"

# transition(**fields)로 바꿀 수 있는 jobs 컬럼 (컬럼명을 SQL에 넣으므로 화이트리스트로 제한)
JOB_FIELDS = frozenset({
    "topic_id", "format_id", "config_version", "attempt", "qa_rounds", "cost_usd", "error",
    "lease_owner", "lease_until", "requested_topic",
})


class _Result:
    def __init__(self, rows: list[sqlite3.Row], rowcount: int, lastrowid: int | None):
        self._rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchone(self) -> sqlite3.Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[sqlite3.Row]:
        return self._rows


class SqliteStore:
    def __init__(self, path: str | Path = ":memory:", clock: Clock | None = None,
                 schema_path: Path = SCHEMA_PATH):
        self.path = str(path)
        self.clock = clock or SystemClock()
        # isolation_level=None: 문장마다 자동 커밋 → UPDATE 한 문장이 곧 트랜잭션
        self._conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")  # D1 기본값과 맞춤
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._migrate(schema_path)

    # ------------------------------------------------------------ 내부
    def _migrate(self, schema_path: Path) -> None:
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
            if not exists:
                self._conn.executescript(schema_path.read_text(encoding="utf-8"))

    def _exec(self, sql: str, params: tuple | list = ()) -> "_Result":
        # 결과를 잠금 안에서 모두 읽어, 연결 하나를 여러 스레드가 써도 섞이지 않게 한다.
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            return _Result(rows, cur.rowcount, cur.lastrowid)

    def _now(self) -> str:
        return db_time(self.clock.now())

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------ jobs
    def create_job(self, origin: str, requested_topic: str | None = None, format_id: str | None = None,
                   job_id: str | None = None, config_version: str | None = None) -> Job:
        job_id = job_id or new_ulid(self.clock.now())
        now = self._now()
        self._exec(
            "INSERT INTO jobs (id, origin, requested_topic, format_id, config_version, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, origin, requested_topic, format_id, config_version, now, now),
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job:
        row = self._exec("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job 없음: {job_id}")
        return Job(**dict(row))

    def list_jobs(self, state: str | None = None, limit: int = 20) -> list[Job]:
        if state:
            rows = self._exec(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC, id DESC LIMIT ?", (state, limit)
            ).fetchall()
        else:
            rows = self._exec("SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [Job(**dict(r)) for r in rows]

    def acquire_lease(self, job_id: str, owner: str, ttl_sec: int) -> bool:
        """비어 있거나 만료됐거나 내 lease면 (재)획득한다. 같은 owner가 부르면 연장."""
        now_dt = self.clock.now()
        now, until = db_time(now_dt), db_time(now_dt + timedelta(seconds=ttl_sec))
        cur = self._exec(
            "UPDATE jobs SET lease_owner = ?, lease_until = ?, updated_at = ?"
            " WHERE id = ? AND (lease_owner IS NULL OR lease_until IS NULL OR lease_until <= ? OR lease_owner = ?)",
            (owner, until, now, job_id, now, owner),
        )
        return cur.rowcount == 1

    def release_lease(self, job_id: str, owner: str) -> None:
        self._exec(
            "UPDATE jobs SET lease_owner = NULL, lease_until = NULL, updated_at = ?"
            " WHERE id = ? AND lease_owner = ?",
            (self._now(), job_id, owner),
        )

    def transition(self, job_id: str, frm: str, to: str, *, owner: str | None = None, **fields: Any) -> bool:
        """조건부 전이. 현재 상태가 frm 이고 (owner를 주면) lease가 유효할 때만 바뀐다."""
        check_transition(frm, to)
        unknown = set(fields) - JOB_FIELDS
        if unknown:
            raise ValueError(f"바꿀 수 없는 필드: {sorted(unknown)}")
        now = self._now()
        sets = ["state = ?", "updated_at = ?"] + [f"{k} = ?" for k in fields]
        params: list[Any] = [to, now, *fields.values()]
        where = "id = ? AND state = ?"
        params += [job_id, frm]
        if owner is not None:
            where += " AND lease_owner = ? AND lease_until > ?"
            params += [owner, now]
        cur = self._exec(f"UPDATE jobs SET {', '.join(sets)} WHERE {where}", params)
        return cur.rowcount == 1

    def bump_attempt(self, job_id: str) -> None:
        self._exec("UPDATE jobs SET attempt = attempt + 1, updated_at = ? WHERE id = ?", (self._now(), job_id))

    # ------------------------------------------------------------ 기록
    def record_step(self, run: StepRun) -> int:
        if run.id is None:
            cur = self._exec(
                "INSERT INTO step_runs (job_id, step, role, status, input_hash, cost_usd, tokens_in, tokens_out,"
                " gh_run_id, started_at, ended_at, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.job_id, run.step, run.role, run.status, run.input_hash, run.cost_usd, run.tokens_in,
                 run.tokens_out, run.gh_run_id, run.started_at or self._now(), run.ended_at, run.error),
            )
            return int(cur.lastrowid)
        self._exec(
            "UPDATE step_runs SET status = ?, cost_usd = ?, tokens_in = ?, tokens_out = ?, ended_at = ?, error = ?"
            " WHERE id = ?",
            (run.status, run.cost_usd, run.tokens_in, run.tokens_out, run.ended_at or self._now(), run.error, run.id),
        )
        return run.id

    def step_runs(self, job_id: str) -> list[StepRun]:
        rows = self._exec("SELECT * FROM step_runs WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
        return [StepRun(**dict(r)) for r in rows]

    def record_run(self, job_id: str, role: str, cost_usd: float, usage: dict) -> None:
        """역할 실행 비용을 job 합계에 더한다 (원자적 증가)."""
        self._exec(
            "UPDATE jobs SET cost_usd = cost_usd + ?, updated_at = ? WHERE id = ?",
            (float(cost_usd), self._now(), job_id),
        )

    def put_artifact(self, a: Artifact) -> None:
        self._exec(
            "INSERT OR REPLACE INTO artifacts (job_id, kind, scene, r2_key, provider, cost_usd, checks, content_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (a.job_id, a.kind, a.scene, a.r2_key, a.provider, a.cost_usd,
             json.dumps(a.checks, ensure_ascii=False) if a.checks is not None else None, a.content_hash),
        )

    def artifacts(self, job_id: str, kind: str | None = None) -> list[Artifact]:
        if kind:
            rows = self._exec(
                "SELECT * FROM artifacts WHERE job_id = ? AND kind = ? ORDER BY scene", (job_id, kind)
            ).fetchall()
        else:
            rows = self._exec("SELECT * FROM artifacts WHERE job_id = ? ORDER BY kind, scene", (job_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["checks"] = json.loads(d["checks"]) if d["checks"] else None
            out.append(Artifact(**d))
        return out

    def add_evals(self, job_id: str, rubric_version: str, scores: dict[str, float], judge: str) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO evals (job_id, rubric_version, item, score, judge) VALUES (?, ?, ?, ?, ?)",
                [(job_id, rubric_version, item, float(score), judge) for item, score in scores.items()],
            )

    def add_topic(self, t: Topic) -> Topic:
        """norm_hash 가 같은 주제가 있으면 새로 넣지 않고 기존 행을 돌려준다."""
        self._exec(
            "INSERT OR IGNORE INTO topics (id, title, norm_hash, source, angle, evidence_url, score, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (t.id, t.title, t.norm_hash, t.source, t.angle, t.evidence_url, t.score, t.status,
             t.created_at or self._now()),
        )
        row = self._exec("SELECT * FROM topics WHERE norm_hash = ?", (t.norm_hash,)).fetchone()
        return Topic(**dict(row))

    def add_decision(self, job_id: str | None, role: str, action: str, reason: str | None = None) -> None:
        self._exec(
            "INSERT INTO decisions (job_id, role, action, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, role, action, reason, self._now()),
        )

    def add_event(self, kind: str, payload: str | None = None) -> None:
        self._exec("INSERT INTO events (kind, payload, created_at) VALUES (?, ?, ?)", (kind, payload, self._now()))

    # ------------------------------------------------------------ 승인·게시
    def put_approval(self, a: Approval) -> None:
        self._exec(
            "INSERT OR REPLACE INTO approvals (job_id, decision, reason, decided_at) VALUES (?, ?, ?, ?)",
            (a.job_id, a.decision, a.reason, a.decided_at or self._now()),
        )

    def approval(self, job_id: str) -> Approval | None:
        row = self._exec("SELECT * FROM approvals WHERE job_id = ?", (job_id,)).fetchone()
        return Approval(**dict(row)) if row else None

    def upsert_publication(self, p: Publication) -> None:
        self._exec(
            "INSERT INTO publications (job_id, platform, post_id, status, published_at, error)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(job_id, platform) DO UPDATE SET post_id = excluded.post_id, status = excluded.status,"
            " published_at = excluded.published_at, error = excluded.error",
            (p.job_id, p.platform, p.post_id, p.status, p.published_at, p.error),
        )

    # ------------------------------------------------------------ 설정·비용·조회
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._exec("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def month_cost(self) -> float:
        """이번 달(UTC) 생성된 job 비용 합계."""
        month_start = self.clock.now().strftime("%Y-%m-01 00:00:00")
        row = self._exec(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM jobs WHERE created_at >= ?", (month_start,)
        ).fetchone()
        return float(row["total"])

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """분석용 읽기 전용 쿼리 (analyst 의 db_query 도구가 쓴다)."""
        head = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
        if head not in ("select", "with"):
            raise ValueError("query()는 SELECT만 허용합니다")
        with self._lock:
            self._conn.execute("PRAGMA query_only = ON")
            try:
                rows = self._conn.execute(sql, params or []).fetchall()
            finally:
                self._conn.execute("PRAGMA query_only = OFF")
        return [dict(r) for r in rows]
