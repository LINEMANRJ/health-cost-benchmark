"""Teste de ponta a ponta do chat do site (navegador real + Python no navegador via Pyodide).

As APIs dos provedores são interceptadas com respostas simuladas (sem custo e sem chave real).
Verifica: carregamento do Pyodide e do pacote do projeto, loop de tool use com Claude e Cohere,
cabeçalhos e corpo das requisições, renderização segura (sem injeção de script), grounding e
ausência de erros no console (inclusive violações da Content-Security-Policy).

Pré-requisitos: `pip install playwright` + Chromium, e o site gerado com o chat:
    python scripts/build_site.py --pyodide-dir <pyodide extraído>
    python scripts/e2e_site_chat.py [--chromium /caminho/chrome]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FAKE_NUMBER = "123.456,78"


def _br(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fulfill(route: Route, payload: dict) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload),
                  headers={"access-control-allow-origin": "*"})


class FakeProviders:
    """Respostas roteirizadas: 1ª chamada pede uma ferramenta; 2ª responde usando o resultado."""

    def __init__(self) -> None:
        self.requests: dict[str, list[dict]] = {"anthropic": [], "cohere": []}

    def anthropic(self, route: Route) -> None:
        body = json.loads(route.request.post_data)
        self.requests["anthropic"].append({"headers": route.request.headers, "body": body})
        last = body["messages"][-1]
        usage = {"input_tokens": 3000, "output_tokens": 80, "cache_read_input_tokens": 2500}
        if isinstance(last["content"], str):
            tool = {"type": "tool_use", "id": "tu1", "name": "compare_periods",
                    "input": {"periodo_a": {"inicio": "2023-01", "fim": "2023-12"},
                              "periodo_b": {"inicio": "2024-01", "fim": "2024-12"}}}
            _fulfill(route, {"id": "m1", "type": "message", "role": "assistant", "model": "claude-opus-5",
                             "stop_reason": "tool_use", "content": [tool], "usage": usage})
            return
        total = json.loads(last["content"][0]["content"])["total"]
        text = ("**O aumento veio do custo unitário.**\n\n| Efeito | Valor |\n|---|---|\n"
                f"| Custo unitário | R$ {_br(total['efeito_custo_unitario'])} |\n"
                f"| Mix | R$ {_br(total['efeito_mix'])} |\n\n"
                f"Número inventado: R$ {FAKE_NUMBER}. <script>alert(1)</script>")
        _fulfill(route, {"id": "m2", "type": "message", "role": "assistant", "model": "claude-opus-5",
                         "stop_reason": "end_turn", "content": [{"type": "text", "text": text}], "usage": usage})

    def cohere(self, route: Route) -> None:
        body = json.loads(route.request.post_data)
        self.requests["cohere"].append({"headers": route.request.headers, "body": body})
        last = body["messages"][-1]
        usage = {"tokens": {"input_tokens": 900, "output_tokens": 30}}
        if last["role"] == "user":
            args = {"dimension": "uf_sigla", "order_by": "indice_custo_ajustado", "limit": 3}
            function = {"name": "compare_by", "arguments": json.dumps(args)}
            call = {"id": "call1", "type": "function", "function": function}
            _fulfill(route, {"id": "c1", "finish_reason": "TOOL_CALL", "usage": usage,
                             "message": {"role": "assistant", "tool_plan": "Comparar UFs.", "tool_calls": [call]}})
            return
        top = last["content"][0]["document"]["data"]["resultado"][0]
        index = str(top["indice_custo_ajustado"]).replace(".", ",")
        text = f"{top['uf_sigla']} lidera com índice {index}."
        _fulfill(route, {"id": "c2", "finish_reason": "COMPLETE", "usage": usage,
                         "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


def run(url: str, chromium: str | None) -> int:
    fake = FakeProviders()
    logs: list[str] = []
    dialogs: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium) if chromium else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1400})
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        page.route("https://api.anthropic.com/**", fake.anthropic)
        page.route("https://api.cohere.com/**", fake.cohere)
        page.goto(url)
        page.wait_for_timeout(1500)

        page.locator(".chat-example").first.click()  # sem chave: deve pedir a chave
        no_key_status = page.locator("#chat-status").inner_text()

        page.fill("#chat-key", "sk-ant-TESTE")
        page.locator(".chat-example").first.click()
        page.wait_for_selector(".chat-assistant details", timeout=240_000)
        claude_answer = page.locator(".chat-assistant").nth(0)
        claude_text = claude_answer.inner_text()
        injected_scripts = claude_answer.locator("script").count()
        tables = claude_answer.locator("table").count()

        page.check("input[value=cohere]")
        page.fill("#chat-key", "co-TESTE")
        page.fill("#chat-input", "Quais UFs gastam mais que o esperado?")
        page.click("#chat-form button")
        page.wait_for_function("document.querySelectorAll('.chat-assistant details').length >= 2", timeout=120_000)
        cohere_answer = page.locator(".chat-assistant").last.inner_text()

        browser.close()

    a, c = fake.requests["anthropic"], fake.requests["cohere"]
    errors = [line for line in logs if line.startswith(("error", "pageerror")) or "Content Security Policy" in line]
    checks = {
        "pede a chave antes de consultar": "chave" in no_key_status.lower(),
        "Claude: tabela renderizada": tables == 1,
        "Claude: grounding sinalizou número inventado": f"Números sem correspondência nas ferramentas: {FAKE_NUMBER}"
                                                         in claude_text,
        "sem script injetado": injected_scripts == 0 and not dialogs,
        "Claude: cabeçalhos (CORS, versão, fallback)": a[0]["headers"].get("anthropic-dangerous-direct-browser-access")
        == "true" and a[0]["headers"].get("anthropic-beta") == "server-side-fallback-2026-07-01",
        "Claude: 10 ferramentas e cache no system": len(a[0]["body"]["tools"]) == 10
        and a[0]["body"]["system"][0]["cache_control"] == {"type": "ephemeral"},
        "chave nunca no corpo": all("sk-ant-TESTE" not in json.dumps(r["body"]) for r in a),
        "Cohere: Bearer + papéis corretos": c[0]["headers"].get("authorization") == "Bearer co-TESTE"
        and [m["role"] for m in c[1]["body"]["messages"]] == ["system", "user", "assistant", "tool"],
        "Cohere: resposta fundamentada": "Todos os números conferem" in cohere_answer,
        "sem erros no console / CSP": not errors,
    }
    for name, ok in checks.items():
        print(("OK    " if ok else "FALHA ") + name)
    if errors:
        print("\n".join(errors[:10]))
    return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chromium", default=None, help="Executável do Chromium (padrão: o do Playwright)")
    parser.add_argument("--site", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    if not (args.site / "chat.js").exists():
        print("Site sem chat. Gere com: python scripts/build_site.py --pyodide-dir <pyodide extraído>")
        return 2
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    handler = functools.partial(QuietHandler, directory=str(args.site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        return run(f"http://127.0.0.1:{server.server_port}/#agente", args.chromium)
    finally:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
