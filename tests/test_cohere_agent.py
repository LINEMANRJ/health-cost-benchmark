"""Testes do agente Cohere: cliente simulado e SDK oficial `cohere` contra servidor HTTP local."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

import pytest

from hcb.ai import tools
from hcb.ai.agent import AgentError, Conversation
from hcb.ai.cohere_agent import CohereHealthCostAgent, _parse_args, cohere_tools


def _resp(finish, text=None, calls=None, plan=None):
    content = [NS(type="text", text=text)] if text is not None else None
    tool_calls = [NS(id=cid, type="function", function=NS(name=name, arguments=json.dumps(args)))
                  for cid, name, args in (calls or [])] or None
    usage = NS(tokens=NS(input_tokens=100, output_tokens=10), billed_units=None, cached_tokens=30)
    return NS(finish_reason=finish, message=NS(content=content, tool_calls=tool_calls, tool_plan=plan), usage=usage)


class FakeCohere:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def chat(self, **kwargs):
        self.calls.append({**kwargs, "messages": json.loads(json.dumps(kwargs["messages"], default=str))})
        step = self.script.pop(0)
        return step(kwargs["messages"]) if callable(step) else step


def test_cohere_tool_format_matches_specs():
    specs = cohere_tools()
    assert {s["function"]["name"] for s in specs} == set(tools.TOOLS)
    assert all(s["type"] == "function" for s in specs)
    blob = json.dumps(specs)
    assert '"type": ["' not in blob  # tipos em lista simplificados


def test_cohere_agent_loop(clean_fact, tmp_path):
    def final(messages):
        doc = messages[-1]["content"][0]["document"]["data"]
        return _resp("COMPLETE", text=f"Maior índice: {doc['resultado'][0]['regiao']}.")

    client = FakeCohere([
        _resp("TOOL_CALL", plan="Vou comparar as regiões.",
              calls=[("c1", "compare_by", {"dimension": "regiao", "order_by": "indice_custo_ajustado", "limit": 1})]),
        final,
    ])
    agent = CohereHealthCostAgent(clean_fact, client=client, audit_log=tmp_path / "a.jsonl")
    result = agent.ask("Qual região tem maior índice ajustado?")

    assert result.provider == "cohere" and result.stop_reason == "COMPLETE"
    assert result.answer.startswith("Maior índice:") and result.tool_calls[0].ok
    assert result.usage["input_tokens"] == 200 and result.usage["cache_read_input_tokens"] == 60
    first = client.calls[0]
    assert first["model"] == "command-a-plus-05-2026"
    assert first["messages"][0]["role"] == "system" and first["messages"][1]["role"] == "user"
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
    assert second[2]["tool_calls"][0]["function"]["name"] == "compare_by"
    assert second[3]["tool_call_id"] == "c1"
    assert json.loads((tmp_path / "a.jsonl").read_text(encoding="utf-8"))["provider"] == "cohere"


def test_cohere_tool_errors_and_bad_json(clean_fact):
    bad = NS(id="c2", type="function", function=NS(name="get_kpis", arguments="{nao é json"))
    step1 = _resp("TOOL_CALL", calls=[("c1", "get_kpis", {"filters": {"senha": 1}})])
    step1.message.tool_calls.append(bad)
    client = FakeCohere([step1, _resp("COMPLETE", text="Tratado.")])
    result = CohereHealthCostAgent(clean_fact, client=client).ask("x")
    assert [c.ok for c in result.tool_calls] == [False, False]
    tool_msgs = [m for m in client.calls[1]["messages"] if m["role"] == "tool"]
    assert all("erro" in m["content"][0]["document"]["data"] for m in tool_msgs)


def test_cohere_max_steps_and_errors(clean_fact):
    loop = [_resp("TOOL_CALL", calls=[(f"c{i}", "list_dimensions", {})]) for i in range(2)]
    conv = Conversation()
    r = CohereHealthCostAgent(clean_fact, client=FakeCohere(loop), max_steps=2).ask("loop", conv)
    assert r.stop_reason == "max_steps" and conv.messages[-1]["role"] == "assistant"

    agent = CohereHealthCostAgent(clean_fact, client=FakeCohere([]))

    def boom(messages):
        raise AgentError("sem chave")

    agent._chat = boom
    conv2 = Conversation()
    with pytest.raises(AgentError):
        agent.ask("p", conv2)
    assert [m["role"] for m in conv2.messages] == ["system", "user", "assistant"]


def test_cohere_grounding_flags_invented_numbers(clean_fact):
    client = FakeCohere([_resp("TOOL_CALL", calls=[("c1", "get_kpis", {})]),
                         _resp("COMPLETE", text="O custo médio é R$ 7.777,77.")])
    assert CohereHealthCostAgent(clean_fact, client=client).ask("custo?").ungrounded == ["7.777,77"]


def test_parse_args():
    assert _parse_args('{"a": 1}') == {"a": 1}
    assert _parse_args("[1, 2]") == {}
    assert "__argumentos_invalidos__" in _parse_args("{quebrado")


def test_missing_key_raises_agent_error(clean_fact, monkeypatch):
    pytest.importorskip("cohere")
    monkeypatch.delenv("CO_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    with pytest.raises(AgentError, match="CO_API_KEY"):
        CohereHealthCostAgent(clean_fact).ask("pergunta")


# --------------------------------------------------------------------------- SDK real + servidor local
class _Handler(BaseHTTPRequestHandler):
    requests: list = []
    responses: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        payload = json.dumps(type(self).responses.pop(0)).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def test_cohere_agent_with_real_sdk(clean_fact):
    cohere = pytest.importorskip("cohere")
    _Handler.requests = []
    _Handler.responses = [
        {"id": "r1", "finish_reason": "TOOL_CALL",
         "message": {"role": "assistant", "tool_plan": "Consultar KPIs.",
                     "tool_calls": [{"id": "call_1", "type": "function",
                                     "function": {"name": "get_kpis",
                                                  "arguments": json.dumps({"filters": {"regiao": "Sul"}})}}]},
         "usage": {"tokens": {"input_tokens": 50, "output_tokens": 5}}},
        {"id": "r2", "finish_reason": "COMPLETE",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Resposta final."}]},
         "usage": {"tokens": {"input_tokens": 60, "output_tokens": 8}}},
    ]
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = cohere.ClientV2(api_key="test-key", base_url=f"http://127.0.0.1:{server.server_port}")
        result = CohereHealthCostAgent(clean_fact, client=client).ask("KPIs do Sul?")
    finally:
        server.shutdown()

    assert result.answer == "Resposta final." and result.tool_calls[0].ok
    first, second = _Handler.requests
    assert first["path"].endswith("/v2/chat")
    assert first["headers"].get("Authorization", first["headers"].get("authorization")) == "Bearer test-key"
    assert "test-key" not in json.dumps(first["body"])
    assert first["body"]["tools"][0]["type"] == "function"
    roles = [m["role"] for m in second["body"]["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    tool_msg = second["body"]["messages"][3]
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"][0]["document"]["data"]["internacoes"] > 0
