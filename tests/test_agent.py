"""Testes do agente com um cliente simulado (sem chamadas reais à API)."""
import json
from types import SimpleNamespace

import pytest

from hcb.ai import tools
from hcb.ai.agent import Conversation, HealthCostAgent
from hcb.ai.grounding import extract_numbers, ungrounded_numbers


# --------------------------------------------------------------------------- cliente simulado
def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(id_, name, inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def _resp(content, stop):
    usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=80,
                            cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage, model="claude-opus-5")


class FakeClient:
    """Devolve respostas roteirizadas; a resposta final pode ser função das mensagens recebidas."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # cópia do histórico no momento
        step = self.script.pop(0)
        return step(kwargs["messages"]) if callable(step) else step


def _last_tool_results(messages):
    return messages[-1]["content"]


# --------------------------------------------------------------------------- agente
def test_agent_runs_tool_loop_and_grounds_answer(clean_fact, tmp_path):
    def final(messages):
        payload = json.loads(_last_tool_results(messages)[0]["content"])
        cost = f"{payload['custo_medio_por_internacao']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return _resp([_text(f"O custo médio por internação é R$ {cost}.")], "end_turn")

    client = FakeClient([_resp([_tool("t1", "get_kpis", {"filters": {"regiao": "Sul"}})], "tool_use"), final])
    agent = HealthCostAgent(clean_fact, client=client, audit_log=tmp_path / "audit.jsonl")
    result = agent.ask("Qual o custo médio no Sul?")

    assert result.stop_reason == "end_turn"
    assert result.steps == 2
    assert [c.name for c in result.tool_calls] == ["get_kpis"] and result.tool_calls[0].ok
    assert result.grounded, result.ungrounded
    assert result.usage["cache_read_input_tokens"] == 160
    # Requisição: ferramentas, system com cache, fallback server-side.
    req = client.calls[0]
    assert req["model"] == "claude-opus-5"
    assert {t["name"] for t in req["tools"]} == set(tools.TOOLS)
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert audit[0]["question"] == "Qual o custo médio no Sul?" and audit[0]["tool_calls"][0]["name"] == "get_kpis"


def test_agent_flags_invented_numbers(clean_fact):
    client = FakeClient([
        _resp([_tool("t1", "get_kpis", {})], "tool_use"),
        _resp([_text("O custo médio é R$ 9.999,99 e cresceu 42,0%.")], "end_turn"),
    ])
    result = HealthCostAgent(clean_fact, client=client).ask("custo?")
    assert result.ungrounded == ["9.999,99", "42,0%"]


def test_tool_errors_are_returned_to_model(clean_fact):
    client = FakeClient([
        _resp([_tool("t1", "get_kpis", {"filters": {"senha": "x"}}), _tool("t2", "nao_existe", {})], "tool_use"),
        lambda messages: _resp([_text(f"{len(_last_tool_results(messages))} erros tratados")], "end_turn"),
    ])
    result = HealthCostAgent(clean_fact, client=client).ask("teste")
    assert [c.ok for c in result.tool_calls] == [False, False]
    tool_results = client.calls[1]["messages"][-1]["content"]
    assert all(r["is_error"] for r in tool_results)  # ambos no MESMO turno de usuário
    assert "Filtro não suportado" in tool_results[0]["content"]


def test_agent_stops_at_max_steps(clean_fact):
    client = FakeClient([_resp([_tool(f"t{i}", "list_dimensions", {})], "tool_use") for i in range(3)])
    conv = Conversation()
    result = HealthCostAgent(clean_fact, client=client, max_steps=3).ask("loop", conv)
    assert result.stop_reason == "max_steps" and result.steps == 3
    assert "Interrompido após 3 etapas" in result.answer
    assert conv.messages[-1]["role"] == "assistant"  # histórico continua válido


def test_refusal_is_handled(clean_fact):
    client = FakeClient([_resp([], "refusal")])
    result = HealthCostAgent(clean_fact, client=client).ask("algo fora do escopo")
    assert result.stop_reason == "refusal" and "recusou" in result.answer


def test_multi_turn_conversation_is_append_only(clean_fact):
    client = FakeClient([_resp([_text("Primeira.")], "end_turn"), _resp([_text("Segunda.")], "end_turn")])
    agent, conv = HealthCostAgent(clean_fact, client=client), Conversation()
    agent.ask("p1", conv)
    snapshot = list(conv.messages)
    agent.ask("p2", conv)
    assert conv.messages[: len(snapshot)] == snapshot
    assert [m["role"] for m in conv.messages] == ["user", "assistant", "user", "assistant"]


def test_empty_question_rejected(clean_fact):
    with pytest.raises(ValueError):
        HealthCostAgent(clean_fact, client=FakeClient([])).ask("  ")


def test_system_prompt_is_stable_and_lists_codes(clean_fact):
    a = HealthCostAgent(clean_fact, client=FakeClient([]))
    b = HealthCostAgent(clean_fact, client=FakeClient([]))
    assert a.system_prompt == b.system_prompt  # estável → cacheável
    assert "0406" in a.system_prompt and "SINTÉTICA" in a.system_prompt


# --------------------------------------------------------------------------- ferramentas
def test_compare_periods_decomposition_is_exact(clean_fact):
    out = tools.compare_periods(clean_fact, {"inicio": "2022-01", "fim": "2022-12"},
                                {"inicio": "2023-01", "fim": "2023-12"}, by="regiao")
    t = out["total"]
    effects = t["efeito_volume"] + t["efeito_mix"] + t["efeito_custo_unitario"]
    assert effects == pytest.approx(t["variacao_valor"], rel=1e-6)
    assert t["efeito_custo_unitario"] > 0  # base sintética tem reajuste nominal
    assert len(out["por_regiao"]) == 5


def test_tool_input_validation(clean_fact):
    with pytest.raises(tools.ToolInputError):
        tools.call_tool(clean_fact, "compare_periods", {"periodo_a": {"inicio": "2022/01"}, "periodo_b": {}})
    with pytest.raises(tools.ToolInputError):
        tools.call_tool(clean_fact, "compare_by", {"dimension": "senha"})
    with pytest.raises(tools.ToolInputError):
        tools.call_tool(clean_fact, "get_kpis", {"filtros_errados": {}})
    with pytest.raises(tools.ToolInputError):
        tools.call_tool(clean_fact, "list_outliers", {"z_threshold": 50})


def test_all_tools_return_json_serializable(clean_fact):
    args = {"compare_by": {"dimension": "uf_sigla", "order_by": "indice_custo_ajustado", "limit": 5},
            "concentration": {"dimension": "subgrupo_nome"},
            "compare_periods": {"periodo_a": {"inicio": "2022-01", "fim": "2022-06"},
                                "periodo_b": {"inicio": "2023-01", "fim": "2023-06"}},
            "monthly_series": {"filters": {"competencia_inicio": "2023-07"}, "by": "regiao"}}
    for name in tools.TOOLS:
        out = tools.call_tool(clean_fact, name, args.get(name, {}))
        json.dumps(out, allow_nan=False)


# --------------------------------------------------------------------------- grounding
def test_grounding_parses_brazilian_formats():
    values = [m.value for m in extract_numbers("R$ 1.234,56; 6,1%; 35.535.036; R$ 65,9 bi; 2024; 0406; 12 meses")]
    assert values[:3] == [1234.56, 6.1, 35535036.0]
    assert values[3] == pytest.approx(65.9e9)
    assert len(values) == 4  # ano, código SIGTAP e janela de meses ignorados


def test_grounding_accepts_rounding_and_fractions():
    outputs = [{"custo": 1854.7309, "var": 0.06121, "total": 65907927963.75, "idx": [1.0934]}]
    assert ungrounded_numbers("R$ 1.854,73, +6,1%, R$ 65,9 bi, índice 1,093", outputs) == []
    assert ungrounded_numbers("índice 1,20", outputs) == ["1,20"]


def test_api_error_keeps_history_valid(clean_fact):
    from hcb.ai.agent import AgentError

    agent = HealthCostAgent(clean_fact, client=FakeClient([]))

    def boom(messages):
        raise AgentError("sem credencial")

    agent._create = boom
    conv = Conversation()
    with pytest.raises(AgentError):
        agent.ask("pergunta", conv)
    assert [m["role"] for m in conv.messages] == ["user", "assistant"]
