"""Agente "Pergunte aos dados" usando a API da Cohere (Chat v2 com tool use).

Mesma arquitetura do agente Claude (`hcb.ai.agent`): o modelo apenas escolhe ferramentas; os
números vêm das funções determinísticas de `hcb.ai.tools`, e toda resposta passa pela
verificação numérica de `hcb.ai.grounding`. Muda só o provedor e o formato das mensagens:

- ferramentas no formato `{"type": "function", "function": {name, description, parameters}}`;
- o modelo devolve `finish_reason="TOOL_CALL"` com `message.tool_plan` e `message.tool_calls`
  (argumentos em JSON string);
- os resultados voltam como mensagens `{"role": "tool", "tool_call_id", "content": [documento]}`.

Credencial: variável de ambiente CO_API_KEY (lida pelo SDK `cohere`), nunca no código.

Uso:
    python -m hcb.ai.cohere_agent "Quais regiões gastam acima do esperado para o seu mix?"
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from hcb.ai import tools as agent_tools
from hcb.ai.agent import (
    MAX_STEPS,
    AgentError,
    AgentResult,
    Conversation,
    ToolCall,
    build_system_prompt,
    execute_tool,
    write_audit,
)
from hcb.ai.grounding import ungrounded_numbers

log = logging.getLogger(__name__)

DEFAULT_MODEL = "command-a-plus-05-2026"
MAX_TOKENS = 8000


def _simplify_schema(schema: Any) -> Any:
    """Adapta o JSON Schema das ferramentas: tipos em lista (ex.: ["string", "array"]) viram o primeiro tipo,
    formato aceito de forma mais ampla pelos provedores. Filtros passam a receber um valor por chave."""
    if isinstance(schema, dict):
        out = {k: _simplify_schema(v) for k, v in schema.items()}
        if isinstance(out.get("type"), list):
            out["type"] = out["type"][0]
        return out
    if isinstance(schema, list):
        return [_simplify_schema(v) for v in schema]
    return schema


def cohere_tools() -> list[dict]:
    """Converte as especificações de `hcb.ai.tools.TOOL_SPECS` para o formato da Cohere v2."""
    return [
        {"type": "function",
         "function": {"name": spec["name"], "description": spec["description"],
                      "parameters": _simplify_schema(copy.deepcopy(spec["input_schema"]))}}
        for spec in agent_tools.TOOL_SPECS
    ]


class CohereHealthCostAgent:
    provider = "cohere"

    def __init__(self, fact: pd.DataFrame, *, synthetic: bool = True, client: Any = None,
                 model: str = DEFAULT_MODEL, max_steps: int = MAX_STEPS, audit_log: Path | None = None) -> None:
        if fact.empty:
            raise ValueError("A tabela fato está vazia.")
        self.fact = fact
        self.model = model
        self.max_steps = max_steps
        self.audit_log = audit_log
        self.system_prompt = build_system_prompt(fact, synthetic)
        self.tools = cohere_tools()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import cohere  # import tardio: o restante do projeto não depende do SDK
            from cohere.core.api_error import ApiError

            try:
                self._client = cohere.ClientV2()  # lê CO_API_KEY do ambiente
            except ApiError as exc:
                raise AgentError("Nenhuma credencial da Cohere encontrada. Defina a variável de ambiente "
                                 "CO_API_KEY.") from exc
        return self._client

    # ------------------------------------------------------------------ modelo
    def _chat(self, messages: list[dict]) -> Any:
        import httpx
        from cohere.core.api_error import ApiError

        client = self.client
        try:
            return client.chat(model=self.model, messages=messages, tools=self.tools, max_tokens=MAX_TOKENS)
        except ApiError as exc:
            status = exc.status_code
            if status in (401, 498):
                raise AgentError("Credencial da Cohere inválida. Verifique CO_API_KEY.") from exc
            if status == 403:
                raise AgentError("A credencial da Cohere não tem permissão para este modelo.") from exc
            if status == 429:
                raise AgentError("Limite de requisições da Cohere atingido. Tente novamente em instantes.") from exc
            raise AgentError(f"Erro da API da Cohere ({status}): {exc.body}") from exc
        except httpx.HTTPError as exc:
            raise AgentError("Não foi possível conectar à API da Cohere. Verifique a rede.") from exc

    # ------------------------------------------------------------------ loop
    def ask(self, question: str, conversation: Conversation | None = None) -> AgentResult:
        question = (question or "").strip()
        if not question:
            raise ValueError("Pergunta vazia.")
        conv = conversation if conversation is not None else Conversation()
        if not conv.messages:
            conv.messages.append({"role": "system", "content": self.system_prompt})
        conv.messages.append({"role": "user", "content": question})

        calls: list[ToolCall] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        answer, finish, steps, model = "", "", 0, self.model

        while True:
            if steps >= self.max_steps:
                finish = "max_steps"
                break
            steps += 1
            try:
                response = self._chat(conv.messages)
            except AgentError:
                conv.messages.append({"role": "assistant", "content": "(consulta interrompida por erro)"})
                raise
            _add_usage(usage, response)
            finish = str(response.finish_reason)
            message = response.message

            if finish == "TOOL_CALL" and message.tool_calls:
                conv.messages.append({
                    "role": "assistant",
                    "tool_plan": message.tool_plan or "",
                    "tool_calls": [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                   for tc in message.tool_calls],
                })
                for tc in message.tool_calls:
                    call = execute_tool(self.fact, tc.function.name, _parse_args(tc.function.arguments))
                    calls.append(call)
                    if call.ok:
                        conv.tool_outputs.append(call.output)
                    conv.messages.append({"role": "tool", "tool_call_id": tc.id, "content": [_document(call)]})
                continue

            answer = "".join(c.text for c in (message.content or []) if getattr(c, "type", None) == "text")
            conv.messages.append({"role": "assistant", "content": answer or "(sem texto)"})
            break

        if finish == "MAX_TOKENS":
            answer += "\n\n_(Resposta interrompida por limite de tamanho.)_"
        elif finish in ("ERROR", "TIMEOUT"):
            answer = "A API da Cohere não concluiu a resposta (erro ou tempo esgotado). Tente novamente."
        elif finish == "max_steps":
            conv.messages.append({"role": "assistant", "content": "(análise interrompida por limite de etapas)"})
            answer = f"_(Interrompido após {self.max_steps} etapas. Reformule a pergunta de forma mais específica.)_"

        result = AgentResult(
            question=question, answer=answer.strip(), tool_calls=calls, steps=steps, stop_reason=finish,
            model=model, usage=usage, ungrounded=ungrounded_numbers(answer, conv.tool_outputs),
            provider=self.provider,
        )
        write_audit(self.audit_log, result)
        return result


def _parse_args(raw: Any) -> dict:
    """Argumentos chegam como JSON string; entrada malformada vira {} e a ferramenta valida."""
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {"__argumentos_invalidos__": str(raw)[:200]}
    return parsed if isinstance(parsed, dict) else {}


def _document(call: ToolCall) -> dict:
    """Resultado da ferramenta como documento Cohere (`data` deve ser um objeto)."""
    if call.ok:
        data = call.output if isinstance(call.output, dict) else {"resultado": call.output}
        return {"type": "document", "document": {"data": json.loads(json.dumps(data, default=str))}}
    return {"type": "document", "document": {"data": {"erro": call.error}}}


def _add_usage(usage: dict[str, int], response: Any) -> None:
    u = getattr(response, "usage", None)
    if u is None:
        return
    tokens = getattr(u, "tokens", None) or getattr(u, "billed_units", None)
    if tokens is not None:
        usage["input_tokens"] += int(getattr(tokens, "input_tokens", 0) or 0)
        usage["output_tokens"] += int(getattr(tokens, "output_tokens", 0) or 0)
    usage["cache_read_input_tokens"] += int(getattr(u, "cached_tokens", 0) or 0)


def from_settings(**kwargs: Any) -> CohereHealthCostAgent:
    from hcb.config import load_settings
    from hcb.pipeline import load_fact

    settings = load_settings()
    kwargs.setdefault("audit_log", settings.reports_dir / "agent_audit.jsonl")
    return CohereHealthCostAgent(load_fact(settings), synthetic=settings.source_type == "synthetic", **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pergunte aos dados do Health Cost Benchmark (Cohere).")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        result = from_settings(model=args.model).ask(" ".join(args.question))
    except AgentError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(result.answer)
    if args.verbose or result.ungrounded:
        print("\n---")
        for c in result.tool_calls:
            status = "ok" if c.ok else f"erro: {c.error}"
            print(f"ferramenta {c.name}({json.dumps(c.input, ensure_ascii=False)}) -> {status} [{c.duration_ms} ms]")
        if result.ungrounded:
            print(f"⚠️ Números sem correspondência nas ferramentas: {', '.join(result.ungrounded)}")
        print(f"etapas={result.steps} tokens_in={result.usage['input_tokens']} "
              f"tokens_out={result.usage['output_tokens']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
