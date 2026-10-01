"""topic_bank — 주제 은행(D1 topics). 최근 주제 조회·중복 확인·후보 저장."""
from __future__ import annotations

from agent.core.clock import new_ulid
from agent.core.models import Topic
from agent.core.ports import Store
from agent.core.text import norm_hash
from agent.tools.base import ToolContext, err, ok


def recent_titles(store: Store, limit: int = 30, exclude_id: str | None = None) -> list[str]:
    rows = store.query(
        "SELECT id, title FROM topics WHERE status = 'used' ORDER BY created_at DESC LIMIT ?", [limit + 1]
    )
    return [r["title"] for r in rows if r["id"] != exclude_id][:limit]


def check(store: Store, title: str) -> dict:
    rows = store.query("SELECT title, status FROM topics WHERE norm_hash = ?", [norm_hash(title)])
    if rows:
        return {"duplicate": True, "existing": rows[0]["title"], "status": rows[0]["status"]}
    return {"duplicate": False}


def put(store: Store, title: str, angle: str | None = None, evidence_url: str | None = None,
        score: float = 0.0, source: str = "web") -> dict:
    t = store.add_topic(Topic(id=new_ulid(), title=title.strip()[:60], norm_hash=norm_hash(title), source=source,
                              angle=angle, evidence_url=evidence_url, score=max(0.0, min(1.0, float(score)))))
    return {"id": t.id, "title": t.title, "status": t.status}


TOPIC_BANK_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["recent", "check", "put"],
               "description": "recent=최근 다룬 제목, check=중복 확인, put=후보 저장"},
        "title": {"type": "string"},
        "angle": {"type": "string"},
        "evidence_url": {"type": "string"},
        "score": {"type": "number"},
    },
    "required": ["op"],
}


def build_topic_bank_tool(tctx: ToolContext):
    from claude_agent_sdk import tool

    @tool("topic_bank", "주제 은행: op=recent(최근 다룬 제목 목록) | check(title 중복 확인) | "
          "put(title, angle, evidence_url, score 저장)", TOPIC_BANK_SCHEMA)
    async def topic_bank(args: dict) -> dict:
        op = args.get("op")
        if op == "recent":
            return ok({"titles": recent_titles(tctx.store)})
        title = (args.get("title") or "").strip()
        if not title:
            return err("title 이 필요합니다")
        if op == "check":
            return ok(check(tctx.store, title))
        if op == "put":
            return ok(put(tctx.store, title, args.get("angle"), args.get("evidence_url"), args.get("score", 0.0)))
        return err(f"알 수 없는 op: {op}")

    return topic_bank
