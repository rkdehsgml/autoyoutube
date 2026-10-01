"""run_role·옵션 구성 테스트 — 가짜 query 로 네트워크 없이."""
import asyncio
import json

import pytest
from fakes import FakeQuery, result_message, storyboard_output

from agent.core.models import ResearchResult, Storyboard
from agent.core.ports import BudgetExceeded, RetryableError
from agent.core.role_runner import RoleFailed, RoleSpec, build_options, output_schema, run_role
from agent.core.settings import PUBLISH_TOOLS, RoleConfig, load_roles


def _tool(name):
    from claude_agent_sdk import tool

    @tool(name, f"{name} 도구", {"type": "object", "properties": {}})
    async def handler(args):
        return {"content": [{"type": "text", "text": "ok"}]}

    return handler


def _spec(role="writer", model=Storyboard, **kw):
    return RoleSpec(config=load_roles()[role], system_prompt="sys", output_model=model, **kw)


def _no_refs(node):
    if isinstance(node, dict):
        assert "$ref" not in node and "$defs" not in node
        for v in node.values():
            _no_refs(v)
    elif isinstance(node, list):
        for v in node:
            _no_refs(v)


def test_output_schema_inlines_refs():
    schema = output_schema(Storyboard)
    _no_refs(schema)
    assert schema["title"] == "Storyboard"
    scene = schema["properties"]["scenes"]["items"]
    assert scene["properties"]["narration"]["maxLength"] == 120  # 제약은 유지 (SDK가 검증·재요청)


def test_researcher_options_restrict_tools():
    spec = _spec("researcher", ResearchResult, mcp_tools=[_tool("topic_bank"), _tool("image_generate")],
                 builtin_tools=["WebSearch", "Bash"])
    opts = build_options(spec)
    cfg = load_roles()["researcher"]
    assert opts.tools == ["WebSearch"]  # Bash 는 설정에 없으니 노출 안 됨
    assert opts.allowed_tools == ["WebSearch", "mcp__autotube__topic_bank"]
    assert set(opts.mcp_servers) == {"autotube"}
    assert opts.permission_mode == "dontAsk" and opts.setting_sources == []
    assert (opts.model, opts.max_turns, opts.max_budget_usd) == (cfg.model, cfg.max_turns, cfg.max_budget_usd)
    assert opts.output_format["type"] == "json_schema"
    assert not PUBLISH_TOOLS & set(opts.allowed_tools)


def test_writer_options_have_no_tools():
    opts = build_options(_spec("writer"))
    assert opts.tools == [] and opts.allowed_tools == [] and opts.mcp_servers == {}


def test_publish_tools_never_exposed():
    with pytest.raises(ValueError):
        build_options(_spec("publisher", mcp_tools=[_tool("publish_youtube")]))
    leaky = RoleConfig(name="x", model="m", max_turns=1, max_budget_usd=0.1, tools=("publish_instagram",))
    with pytest.raises(ValueError):
        build_options(RoleSpec(config=leaky, system_prompt="s", output_model=Storyboard))


def test_run_role_success_records_cost_and_usage():
    fq = FakeQuery({"Storyboard": result_message(storyboard_output(), cost=0.03,
                                                 usage={"input_tokens": 50, "cache_read_input_tokens": 10,
                                                        "output_tokens": 7})})
    res = asyncio.run(run_role(_spec(), {"topic": "x"}, query_fn=fq))
    assert isinstance(res.output, Storyboard)
    assert res.cost_usd == pytest.approx(0.03)
    assert res.usage == {"tokens_in": 60, "tokens_out": 7}
    prompt, opts = fq.calls[0]
    assert '"topic": "x"' in prompt
    assert opts.resume is None


def test_validation_failure_is_fixed_in_same_session():
    bad = storyboard_output()
    bad["hook"] = "가" * 30
    fq = FakeQuery({"Storyboard": [result_message(bad, cost=0.02, session_id="s-9"),
                                   result_message(storyboard_output(), cost=0.01)]})
    res = asyncio.run(run_role(_spec(), {}, query_fn=fq))
    assert res.cost_usd == pytest.approx(0.03)
    prompt2, opts2 = fq.calls[1]
    assert opts2.resume == "s-9" and "검증에 실패" in prompt2 and "hook" in prompt2


def test_validation_failure_twice_raises_with_cost():
    bad = storyboard_output(n=2)
    fq = FakeQuery({"Storyboard": [result_message(bad, cost=0.02), result_message(bad, cost=0.02)]})
    with pytest.raises(RoleFailed) as ei:
        asyncio.run(run_role(_spec(), {}, query_fn=fq))
    assert isinstance(ei.value, RetryableError)
    assert ei.value.cost_usd == pytest.approx(0.04)


@pytest.mark.parametrize("subtype,exc", [
    ("error_max_budget_usd", BudgetExceeded),
    ("error_max_turns", RoleFailed),
    ("error_during_execution", RoleFailed),
])
def test_error_results_are_mapped(subtype, exc):
    fq = FakeQuery({"Storyboard": result_message(None, subtype=subtype, is_error=True, cost=0.05)})
    with pytest.raises(exc) as ei:
        asyncio.run(run_role(_spec(), {}, query_fn=fq))
    assert ei.value.cost_usd == pytest.approx(0.05)


def test_sdk_exception_before_result_is_retryable():
    fq = FakeQuery({"Storyboard": RuntimeError("CLI 연결 실패")})
    with pytest.raises(RoleFailed):
        asyncio.run(run_role(_spec(), {}, query_fn=fq))


def test_exception_after_error_result_uses_result():
    def respond(prompt, options):
        msg = result_message(None, subtype="error_max_budget_usd", is_error=True, cost=0.2)

        async def gen():
            yield msg
            raise RuntimeError("단발 query 는 에러 결과 뒤 예외를 던진다")

        return gen()

    def fake(*, prompt, options):
        return respond(prompt, options)

    with pytest.raises(BudgetExceeded):
        asyncio.run(run_role(_spec(), {}, query_fn=fake))


def test_text_result_fallback_parsing():
    text = "결과입니다:\n```json\n" + json.dumps(storyboard_output(), ensure_ascii=False) + "\n```"
    fq = FakeQuery({"Storyboard": result_message(None, result=text)})
    res = asyncio.run(run_role(_spec(), {}, query_fn=fq))
    assert res.output.title.startswith("제습기")


def test_missing_structured_output_retries_then_fails():
    fq = FakeQuery({"Storyboard": [result_message(None, result="죄송합니다"), result_message(None, result="")]})
    with pytest.raises(RoleFailed):
        asyncio.run(run_role(_spec(), {}, query_fn=fq))
    assert len(fq.calls) == 2
