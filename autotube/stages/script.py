"""대본 생성: LLM → JSON(Script). 공급자는 channel.yaml의 providers.llm으로 교체."""
from __future__ import annotations

import json
import re

import requests

from autotube.config import PROMPT_PATH, Config, env
from autotube.models import Script
from autotube.utils import log

TIMEOUT = 120


def build_prompt(cfg: Config, topic: str, format_id: str, recent: list[str]) -> str:
    fmt = cfg.format_by_id(format_id)
    seconds = cfg.get_path("channel.target_seconds", 45)
    return PROMPT_PATH.read_text(encoding="utf-8").format(
        channel_name=cfg.get_path("channel.name"),
        niche=cfg.get_path("channel.niche"),
        audience=cfg.get_path("channel.audience", ""),
        tone=cfg.get_path("channel.tone"),
        topic=topic,
        format_name=fmt["name"],
        format_structure=fmt["structure"],
        target_seconds=seconds,
        target_chars=int(seconds * 6.5),  # 한국어 내레이션 약 6~7자/초
        recent_titles=", ".join(recent) or "없음",
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def _call_anthropic(prompt: str, model: str) -> str:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _call_gemini(prompt: str, model: str) -> str:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": env("GEMINI_API_KEY")},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_openai(prompt: str, model: str) -> str:
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {env('OPENAI_API_KEY')}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _mock(topic: str) -> dict:
    """API 키 없이 파이프라인 전체를 시험하기 위한 고정 대본."""
    return {
        "title": f"{topic}, 이것만 알면 됩니다",
        "hook": "아직도 이렇게 하세요?",
        "scenes": [
            {"narration": f"{topic}, 대부분 이 부분을 놓칩니다.", "search_query": "messy small apartment"},
            {"narration": "원인은 생각보다 단순합니다. 공기가 순환하지 않기 때문이에요.", "search_query": "window ventilation room"},
            {"narration": "첫 번째 해결책은 제습제처럼 싸고 바로 쓸 수 있는 것부터입니다.", "search_query": "dehumidifier home"},
            {"narration": "두 번째는 서큘레이터로 공기 흐름을 만드는 겁니다.", "search_query": "electric fan room"},
            {"narration": "고를 때는 가격보다 유지비를 먼저 보세요. 이게 제 기준입니다.", "search_query": "shopping online phone"},
        ],
        "products": [
            {"keyword": "옷장 제습제", "reason": "가장 싸고 즉시 효과"},
            {"keyword": "저소음 서큘레이터", "reason": "원룸은 소음이 우선"},
        ],
        "insight": "가격보다 유지비(교체 주기)를 먼저 본다",
        "hashtags": ["#자취", "#생활꿀팁", "#살림템"],
        "description": f"{topic}, 가장 현실적인 해결 순서를 정리했습니다.",
    }


PROVIDERS = {"anthropic": _call_anthropic, "gemini": _call_gemini, "openai": _call_openai}


def generate_script(cfg: Config, topic: str, format_id: str, recent: list[str]) -> Script:
    provider = cfg.get_path("providers.llm", "mock")
    if provider == "mock":
        data = _mock(topic)
    else:
        model = cfg.get_path("providers.llm_model")
        if not model:
            raise RuntimeError("providers.llm_model(또는 LLM_MODEL)에 사용할 모델명을 넣으세요.")
        prompt = build_prompt(cfg, topic, format_id, recent)
        log.info("대본 생성: %s/%s", provider, model)
        data = _extract_json(PROVIDERS[provider](prompt, model))
    data["topic"], data["format_id"] = topic, format_id
    script = Script.from_dict(data)
    if not 2 <= len(script.scenes) <= 10:
        raise ValueError(f"장면 수가 이상합니다: {len(script.scenes)}")
    return script
