"""주제 큐(data/topics.csv): topic,format,status,job_id — status는 todo | done | rejected."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from autotube.config import DATA_DIR

QUEUE_PATH = DATA_DIR / "topics.csv"
FIELDS = ["topic", "format", "status", "job_id"]


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def next_topic(path: Path = QUEUE_PATH) -> dict | None:
    for row in _read(path):
        if row.get("status", "todo") == "todo":
            return row
    return None


def mark(topic: str, status: str, job_id: str = "", path: Path = QUEUE_PATH) -> None:
    rows = _read(path)
    for r in rows:
        if r["topic"] == topic and r.get("status") == "todo":
            r["status"], r["job_id"] = status, job_id
            break
    _write(rows, path)


def add(topic: str, format_id: str = "", path: Path = QUEUE_PATH) -> None:
    rows = _read(path)
    rows.append({"topic": topic, "format": format_id, "status": "todo", "job_id": ""})
    _write(rows, path)


def recent_titles(outputs_dir: Path, limit: int = 20) -> list[str]:
    """최근 생성한 제목 — 대본 프롬프트에 넣어 주제 반복을 막는다."""
    titles = []
    for script in sorted(outputs_dir.glob("*/script.json"), reverse=True)[:limit]:
        titles.append(json.loads(script.read_text(encoding="utf-8")).get("title", ""))
    return [t for t in titles if t]
