"""PlaceholderVisual — 비주얼을 만들지 않는다 (렌더가 단색 배경으로 채움). mock·키 없음용."""
from __future__ import annotations

from pathlib import Path

from agent.core.models import VisualResult, VisualSpec


class PlaceholderVisual:
    name = "placeholder"
    kind = "stock"

    def create(self, spec: VisualSpec, out: Path, exclude: set | None = None) -> VisualResult | None:
        return None
