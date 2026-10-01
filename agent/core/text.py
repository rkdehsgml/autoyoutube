"""문자열 도우미."""
from __future__ import annotations

import hashlib
import re


def norm_hash(title: str) -> str:
    """제목 정규화 해시 — 공백·문장부호·대소문자를 무시하고 같은 주제를 찾는다."""
    norm = re.sub(r"[\s\W_]+", "", title.lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def input_hash(*parts: object) -> str:
    """도구 멱등 키."""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]
