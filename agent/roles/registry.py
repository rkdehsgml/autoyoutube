"""실행 모드별 핸들러 조합.

| 모드  | researcher·writer | producer            | render_video | critic          | publisher(packaging) |
| fast  | mock              | mock(자리표시 바이트) | mock         | mock            | mock                 |
| mock  | mock              | 결정론(MockTTS)      | ffmpeg       | mock            | 코드                 |
| live  | Agent SDK         | Agent SDK + 도구     | ffmpeg       | 임시 통과(3단계) | 코드                 |

fast 는 단위 테스트용, mock 은 기본 실행(외부 호출 없이 진짜 mp4), live 는 --live 를 줄 때만.
"""
from __future__ import annotations

import os
from typing import Callable

from agent.adapters.tts_mock import MockTTS
from agent.core.channel import get_path, load_channel
from agent.core.ports import StepHandler
from agent.roles import critic_stub, editor, packaging, producer, researcher, writer
from agent.roles.deps import RoleDeps
from agent.roles.mock import MockRoles

MODES = ("fast", "mock", "live")


def deps_for(mode: str, channel: dict | None = None, query_fn=None,
             warn: Callable[[str], None] = lambda m: None) -> RoleDeps:
    channel = channel if channel is not None else load_channel()
    if mode != "live":
        return RoleDeps(channel=channel, tts=MockTTS(), stock=None,
                        voice=get_path(channel, "providers.tts_voice", "ko-KR-SunHiNeural"))

    tts_name = get_path(channel, "providers.tts", "edge")
    if tts_name == "google":
        from agent.adapters.tts_google import GoogleTTS
        voice = get_path(channel, "providers.google_voice", "ko-KR-Chirp3-HD-Aoede")
        tts = GoogleTTS(voice=voice)
    elif tts_name == "mock":
        tts, voice = MockTTS(), ""
    else:
        from agent.adapters.tts_edge import EdgeTTS
        tts = EdgeTTS(rate=get_path(channel, "providers.tts_rate", "+0%"))
        voice = get_path(channel, "providers.tts_voice", "ko-KR-SunHiNeural")

    stock = None
    if get_path(channel, "providers.visuals", "pexels") == "pexels":
        if os.getenv("PEXELS_API_KEY"):
            from agent.adapters.visual_pexels import PexelsStock
            stock = PexelsStock()
        else:
            warn("PEXELS_API_KEY 가 없어 비주얼은 단색 배경으로 만듭니다.")
    return RoleDeps(channel=channel, query_fn=query_fn, tts=tts, voice=voice, stock=stock)


def build_handlers(mode: str, deps: RoleDeps | None = None, mock: MockRoles | None = None) -> dict[str, StepHandler]:
    if mode not in MODES:
        raise ValueError(f"알 수 없는 모드: {mode}")
    mock = mock or MockRoles()
    base = mock.handlers()
    if mode == "fast":
        return base
    deps = deps or deps_for(mode)

    def bind(fn, **kw) -> StepHandler:
        async def handler(ctx):
            return await fn(ctx, deps, **kw)
        return handler

    common = {"render_video": bind(editor.run), "publisher": bind(packaging.run)}
    if mode == "mock":
        return {"researcher": base["researcher"], "writer": base["writer"],
                "producer": bind(producer.run, use_llm=False), "critic": base["critic"], **common}
    return {"researcher": bind(researcher.run), "writer": bind(writer.run),
            "producer": bind(producer.run, use_llm=True), "critic": bind(critic_stub.run), **common}
