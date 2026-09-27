"""Integração com o SDK oficial `anthropic` contra um servidor HTTP local que imita a API.

Valida que as requisições montadas pelo agente (ferramentas, cache, fallback, histórico com blocos
do SDK reenviados) são serializadas pelo SDK e que as respostas são interpretadas corretamente —
sem rede e sem custo.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

anthropic = pytest.importorskip("anthropic")

from hcb.ai.agent import HealthCostAgent  # noqa: E402


def _message(content, stop_reason):
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 40,
                      "cache_creation_input_tokens": 0}}


class _Handler(BaseHTTPRequestHandler):
    requests: list = []
    responses: list = []

    def do_POST(self):  # noqa: N802 (nome exigido por BaseHTTPRequestHandler)
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


@pytest.fixture
def fake_api():
    _Handler.requests, _Handler.responses = [], []
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _Handler
    server.shutdown()


def test_agent_with_real_sdk(fake_api, clean_fact):
    base_url, handler = fake_api
    handler.responses = [
        _message([{"type": "tool_use", "id": "toolu_1", "name": "compare_by",
                   "input": {"dimension": "regiao", "order_by": "indice_custo_ajustado", "limit": 2}}], "tool_use"),
        _message([{"type": "text", "text": "Resposta final."}], "end_turn"),
    ]
    client = anthropic.Anthropic(api_key="test-key", base_url=base_url, max_retries=0)
    result = HealthCostAgent(clean_fact, client=client).ask("Quem gasta acima do esperado?")

    assert result.answer == "Resposta final." and result.tool_calls[0].ok
    first, second = handler.requests
    assert first["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in first["headers"].get("anthropic-beta", "")
    assert first["body"]["fallbacks"] == "default"
    assert first["body"]["model"] == "claude-opus-5"
    assert first["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "test-key" not in json.dumps(first["body"])  # credencial só no cabeçalho
    # 2ª chamada: histórico com o bloco tool_use reenviado e o tool_result correspondente.
    msgs = second["body"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"][0]["type"] == "tool_use"
    tool_result = msgs[2]["content"][0]
    assert tool_result["tool_use_id"] == "toolu_1"
    rows = json.loads(tool_result["content"])
    assert len(rows) == 2 and "indice_custo_ajustado" in rows[0]
