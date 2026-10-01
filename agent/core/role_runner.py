"""역할 실행기 — Claude Agent SDK query() 한 번으로 역할 하나를 돌린다.

- 도구 제한: 내장 도구는 `tools`(researcher의 WebSearch만), 커스텀 도구는 in-process MCP 서버
  `autotube`. 노출 범위는 config/roles.yaml 의 tools 와 역할이 제공하는 도구의 교집합.
  permission_mode="dontAsk" 라서 허용 목록 밖의 도구 호출은 전부 거부된다.
- 게시 도구는 어떤 경로로도 allowed_tools 에 들어가지 않는다 (5단계에서 can_use_tool 게이트).
- 출력: Pydantic 모델의 JSON 스키마를 output_format 으로 넘기고, structured_output 을 다시
  Pydantic 으로 검증한다. 실패하면 같은 세션을 이어(resume) 오류를 알려주고 한 번 더 받는다.
- 비용: ResultMessage.total_cost_usd 를 합산해 돌려준다. 실패해도 예외의 cost_usd 에 실어 보낸다.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from pydantic import BaseModel, ValidationError

from agent.core.ports import BudgetExceeded, RetryableError
from agent.core.settings import PUBLISH_TOOLS, RoleConfig

MCP_SERVER = "autotube"
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

QueryFn = Callable[..., AsyncIterator[Any]]  # claude_agent_sdk.query 와 같은 시그니처


class RoleFailed(RetryableError):
    """역할이 쓸 수 있는 출력을 내지 못했다 (재시도 대상)."""


@dataclass
class RoleSpec:
    config: RoleConfig
    system_prompt: str
    output_model: type[BaseModel]
    mcp_tools: list = field(default_factory=list)       # claude_agent_sdk.SdkMcpTool
    builtin_tools: list[str] = field(default_factory=list)  # 예: ["WebSearch"]

    @property
    def name(self) -> str:
        return self.config.name


@dataclass
class RoleResult:
    output: BaseModel
    cost_usd: float
    usage: dict
    num_turns: int
    session_id: str | None = None


def load_prompt(role: str) -> str:
    return (PROMPTS_DIR / f"{role}.md").read_text(encoding="utf-8")


def mcp_tool_name(tool_name: str) -> str:
    return f"mcp__{MCP_SERVER}__{tool_name}"


def output_schema(model: type[BaseModel]) -> dict:
    """$ref 를 펼친 JSON 스키마 (SDK 검증기는 draft-07, $defs 참조를 피한다)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                merged = copy.deepcopy(defs[name])
                merged.update({k: v for k, v in node.items() if k != "$ref"})
                return inline(merged)
            return {k: inline(v) for k, v in node.items()}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return inline(schema)


def build_options(spec: RoleSpec, resume: str | None = None):
    from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server

    allowed_cfg = set(spec.config.tools)
    offered = {t.name for t in spec.mcp_tools} | set(spec.builtin_tools)
    leaked = PUBLISH_TOOLS & (allowed_cfg | offered)
    if leaked:
        raise ValueError(f"게시 도구는 역할 실행에 노출할 수 없습니다: {sorted(leaked)}")
    mcp_tools = [t for t in spec.mcp_tools if t.name in allowed_cfg]
    builtin = [b for b in spec.builtin_tools if b in allowed_cfg]
    allowed = builtin + [mcp_tool_name(t.name) for t in mcp_tools]
    return ClaudeAgentOptions(
        model=spec.config.model,
        system_prompt=spec.system_prompt,
        tools=builtin,                      # 내장 도구: 목록에 있는 것만 ([] = 전부 끔)
        allowed_tools=allowed,
        mcp_servers={MCP_SERVER: create_sdk_mcp_server(MCP_SERVER, tools=mcp_tools)} if mcp_tools else {},
        permission_mode="dontAsk",          # 허용 목록 밖은 묻지 않고 거부
        setting_sources=[],                 # 사용자·프로젝트 설정 파일을 읽지 않음
        max_turns=spec.config.max_turns,
        max_budget_usd=spec.config.max_budget_usd,
        output_format={"type": "json_schema", "schema": output_schema(spec.output_model)},
        resume=resume,
    )


def _prompt(payload: dict) -> str:
    return ("아래 JSON 입력으로 작업하고, 지정된 출력 스키마에 맞는 결과를 내라.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_json(text: str) -> Any:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _summarize(e: ValidationError, limit: int = 8) -> str:
    lines = []
    for err in e.errors()[:limit]:
        loc = ".".join(str(x) for x in err["loc"]) or "(root)"
        lines.append(f"- {loc}: {err['msg']}")
    return "\n".join(lines)


async def _collect(query_fn: QueryFn, prompt: str, options, cost_so_far: float):
    from claude_agent_sdk import ResultMessage

    result = None
    try:
        async for msg in query_fn(prompt=prompt, options=options):
            if isinstance(msg, ResultMessage):
                result = msg
    except Exception as e:  # 단발 query() 는 에러 결과를 내보낸 뒤 예외를 던진다
        if result is None:
            raise RoleFailed(f"SDK 실행 오류: {type(e).__name__}: {e}", cost_usd=cost_so_far) from e
    if result is None:
        raise RoleFailed("SDK가 결과 메시지를 내지 않았습니다", cost_usd=cost_so_far)
    return result


async def run_role(spec: RoleSpec, payload: dict, *, query_fn: QueryFn | None = None,
                   fix_rounds: int = 1) -> RoleResult:
    if query_fn is None:
        from claude_agent_sdk import query as query_fn

    prompt, resume = _prompt(payload), None
    cost, tokens_in, tokens_out, turns = 0.0, 0, 0, 0
    problem = ""
    for _ in range(fix_rounds + 1):
        result = await _collect(query_fn, prompt, build_options(spec, resume), cost)
        cost += float(result.total_cost_usd or 0.0)
        usage = result.usage or {}
        tokens_in += int(usage.get("input_tokens", 0) or 0) + int(usage.get("cache_read_input_tokens", 0) or 0) \
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
        tokens_out += int(usage.get("output_tokens", 0) or 0)
        turns += int(result.num_turns or 0)

        if result.subtype == "error_max_budget_usd":
            raise BudgetExceeded(f"{spec.name} 역할 예산(${spec.config.max_budget_usd:.2f}) 초과로 중단",
                                 cost_usd=cost)
        if result.subtype == "error_max_turns":
            raise RoleFailed(f"{spec.name} 역할이 최대 턴({spec.config.max_turns})에 도달", cost_usd=cost)
        if result.subtype not in ("success", "error_max_structured_output_retries"):
            detail = "; ".join(result.errors or []) or result.subtype
            raise RoleFailed(f"{spec.name} 실행 오류: {detail}", cost_usd=cost)

        data = result.structured_output
        if data is None and result.result:
            data = _parse_json(result.result)
        if data is None:
            problem = "구조화 출력이 없습니다."
        else:
            try:
                out = spec.output_model.model_validate(data)
                return RoleResult(output=out, cost_usd=cost, usage={"tokens_in": tokens_in, "tokens_out": tokens_out},
                                  num_turns=turns, session_id=result.session_id)
            except ValidationError as e:
                problem = _summarize(e)
        resume = result.session_id
        prompt = (f"출력이 스키마 검증에 실패했습니다:\n{problem}\n"
                  "같은 작업 결과를 스키마와 제약(길이·개수)에 맞게 고쳐 다시 출력하라. 도구를 다시 부를 필요는 없다.")
    raise RoleFailed(f"{spec.name} 출력 검증 실패: {problem}", cost_usd=cost)
