"""테스트 대역 — 네트워크 없이 Agent SDK query() 를 흉내 낸다."""
from __future__ import annotations

from typing import Any, Callable

from claude_agent_sdk import ResultMessage


def result_message(structured: Any = None, *, subtype: str = "success", cost: float = 0.01,
                   result: str | None = None, is_error: bool = False, session_id: str = "sess-1",
                   usage: dict | None = None, errors: list[str] | None = None, turns: int = 2) -> ResultMessage:
    return ResultMessage(subtype=subtype, duration_ms=10, duration_api_ms=8, is_error=is_error, num_turns=turns,
                         session_id=session_id, total_cost_usd=cost,
                         usage=usage if usage is not None else {"input_tokens": 100, "output_tokens": 20},
                         result=result, structured_output=structured, errors=errors)


class FakeQuery:
    """claude_agent_sdk.query 대역. 출력 스키마의 title(= Pydantic 모델명)로 응답을 고른다.

    responses: {"Storyboard": [응답, ...] | 응답}. 응답은 ResultMessage, dict(구조화 출력),
    Exception, 또는 (prompt, options) -> 그중 하나를 돌려주는 함수.
    """

    def __init__(self, responses: dict[str, Any]):
        self.responses = {k: (list(v) if isinstance(v, list) else v) for k, v in responses.items()}
        self.calls: list[tuple[str, Any]] = []

    def titles(self) -> list[str]:
        return [opts.output_format["schema"]["title"] for _, opts in self.calls]

    def options_for(self, title: str):
        return next(opts for _, opts in self.calls if opts.output_format["schema"]["title"] == title)

    def __call__(self, *, prompt: str, options: Any):
        self.calls.append((prompt, options))
        title = options.output_format["schema"]["title"]
        resp = self.responses[title]
        item = resp.pop(0) if isinstance(resp, list) else resp
        if isinstance(item, Callable) and not isinstance(item, (ResultMessage, Exception)):
            item = item(prompt, options)

        async def gen():
            if isinstance(item, Exception):
                raise item
            if isinstance(item, ResultMessage):
                yield item
            else:
                yield result_message(item)

        return gen()


def research_output(chosen: int = 0, format_id: str = "myth_fact", requested: str | None = None) -> dict:
    titles = ([requested] if requested else []) + ["제습기 전기세 오해", "빨래 쉰내 원인", "욕실 물때 순서"]
    return {"candidates": [{"title": t, "angle": "기준 제시", "score": 0.9 - i * 0.1,
                            "evidence_url": "https://example.com/a"} for i, t in enumerate(titles)],
            "chosen": chosen, "format_id": format_id}


def storyboard_output(visual: str = "stock", n: int = 5) -> dict:
    return {
        "title": "제습기 전기세, 진짜 폭탄일까",
        "hook": "전기세 폭탄?",
        "scenes": [{"narration": f"장면 {i} 내레이션입니다. 이건 테스트 문장이에요.", "visual": visual,
                    "query_or_prompt": "dehumidifier room", "on_screen_text": "확인!" if i == 0 else "",
                    "target_sec": 4} for i in range(n)],
        "insight": "소비전력보다 사용 시간을 먼저 본다",
        "hashtags": ["#자취", "#제습기", "#생활꿀팁"],
        "description": "제습기 전기세 오해를 정리했습니다.",
        "products": [{"keyword": "저소음 제습기", "reason": "원룸은 소음 우선"}],
    }


def manifest_output(job_id: str, n: int = 5) -> dict:
    return {"scenes": [{"scene": i, "audio_key": f"jobs/{job_id}/audio/scene_{i}.mp3", "visual_key": None,
                        "source": "placeholder", "duration_sec": 3.0} for i in range(n)]}
