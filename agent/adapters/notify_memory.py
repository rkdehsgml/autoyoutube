"""MemoryNotifier — 로컬·테스트용 알림. 텔레그램 대신 메모리에 쌓고, echo=True면 출력도 한다."""
from __future__ import annotations

from pathlib import Path

from agent.core.models import Job, PlatformMeta


class MemoryNotifier:
    def __init__(self, echo: bool = False):
        self.echo = echo
        self.messages: list[str] = []
        self.previews: list[tuple[str, str, str]] = []  # (job_id, video, title)

    def preview(self, job: Job, video: Path, meta: PlatformMeta) -> str:
        self.previews.append((job.id, str(video), meta.youtube.title))
        if self.echo:
            print(f"[미리보기] {job.id} · {meta.youtube.title} · {video}")
        return f"local-{len(self.previews)}"

    def send(self, text: str) -> None:
        self.messages.append(text)
        if self.echo:
            print(f"[알림] {text}")
