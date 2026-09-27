"""Agente de IA para exploração dos dados do Health Cost Benchmark.

O agente usa a API do Claude com *tool use*: o modelo interpreta a pergunta, escolhe e chama
as ferramentas determinísticas de `hcb.ai.tools` (que rodam o mesmo código testado do pipeline)
e redige a resposta a partir dos resultados. Guardrails:

- ferramentas somente leitura, com validação de entrada e limite de linhas;
- limite de etapas por pergunta;
- verificação de fundamentação numérica (`hcb.ai.grounding`) em toda resposta;
- registro de auditoria (JSONL) de cada pergunta, chamada de ferramenta e resposta;
- credenciais apenas via ambiente (ANTHROPIC_API_KEY ou `ant auth login`), nunca no código.

Uso:
    python -m hcb.ai.agent "Quais regiões gastam acima do esperado para o seu mix?"
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from hcb.ai import tools as agent_tools
from hcb.ai.grounding import ungrounded_numbers

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000
MAX_STEPS = 10
# Fallback server-side: se o modelo recusar por política, a API reexecuta no modelo recomendado.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentError(RuntimeError):
    """Falha ao consultar o modelo (credencial, limite de taxa, rede)."""


@dataclass
class ToolCall:
    name: str
    input: dict
    ok: bool
    duration_ms: int
    output: Any = field(repr=False, default=None)
    error: str | None = None


@dataclass
class AgentResult:
    question: str
    answer: str
    tool_calls: list[ToolCall]
    steps: int
    stop_reason: str
    model: str
    ungrounded: list[str]
    usage: dict[str, int]
    provider: str = "anthropic"

    @property
    def grounded(self) -> bool:
        return not self.ungrounded


@dataclass
class Conversation:
    """Histórico multi-turno (somente acréscimos) e saídas de ferramentas já vistas."""

    messages: list[dict] = field(default_factory=list)
    tool_outputs: list[Any] = field(default_factory=list)


def execute_tool(fact: pd.DataFrame, name: str, args: dict) -> ToolCall:
    """Executa uma ferramenta com tratamento de erros comum a todos os provedores de modelo."""
    t0 = time.perf_counter()
    try:
        output = agent_tools.call_tool(fact, name, args)
        return ToolCall(name, args, True, int((time.perf_counter() - t0) * 1000), output)
    except (agent_tools.ToolInputError, KeyError) as exc:
        msg = str(exc).strip("'\"")
    except Exception as exc:  # falha inesperada: o modelo recebe o erro e pode se recuperar
        log.exception("Falha na ferramenta %s", name)
        msg = f"Falha interna ao executar {name}: {type(exc).__name__}"
    return ToolCall(name, args, False, int((time.perf_counter() - t0) * 1000), error=msg)


def tool_result_text(call: ToolCall) -> str:
    return json.dumps(call.output, ensure_ascii=False, default=str) if call.ok else f"Erro: {call.error}"


def write_audit(path: Path | None, result: AgentResult) -> None:
    """Acrescenta a interação ao log de auditoria JSONL (sem credenciais)."""
    if not path:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **{k: v for k, v in asdict(result).items() if k != "tool_calls"},
        "tool_calls": [{"name": c.name, "input": c.input, "ok": c.ok, "duration_ms": c.duration_ms,
                        "error": c.error} for c in result.tool_calls],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        log.warning("Não foi possível gravar o log de auditoria em %s", path)


def build_system_prompt(fact: pd.DataFrame, synthetic: bool) -> str:
    dims = agent_tools.list_dimensions(fact)
    subgroups = "\n".join(f"- {s['subgrupo_codigo']} — {s['subgrupo_nome']} (grupo {s['grupo_codigo']})"
                          for s in dims["subgrupos"])
    data_note = (
        "ATENÇÃO: a base atual é SINTÉTICA (imita a estrutura do SIH/SUS, mas não é dado real). "
        "Mencione isso uma vez quando apresentar resultados numéricos."
        if synthetic else "A base é derivada do SIH/SUS (DATASUS)."
    )
    return f"""Você é um analista de dados de saúde do projeto Health Cost Benchmark. Você responde perguntas \
sobre custos e economicidade de internações hospitalares do SUS usando exclusivamente as ferramentas disponíveis.

## Dados
- Unidade: competência (mês) × UF de internação × subgrupo SIGTAP; valores aprovados de AIH, em R$ nominais.
- Período: {dims['periodo']['inicio']} a {dims['periodo']['fim']} ({dims['periodo']['meses']} meses).
- Regiões: {', '.join(dims['regioes'])}. UFs: {', '.join(dims['ufs'])}.
- Subgrupos SIGTAP:
{subgroups}
- {data_note}

## Regras
1. Todo número da resposta deve vir literalmente de um resultado de ferramenta. Não calcule, estime nem \
invente números; se precisar de um valor que nenhuma ferramenta devolveu, chame outra ferramenta ou diga que \
não há dado. Para perguntas sobre o que explica uma variação do gasto, use compare_periods.
2. Use filtros com os códigos e nomes exatos listados acima. Se a pergunta for ambígua (período, região), \
escolha a interpretação mais razoável e declare-a.
3. Diferenças entre regiões/UFs e correlações são associações, não causas: podem refletir gravidade dos casos, \
rede, fluxo de pacientes ou registro. Atípicos são sinais para verificação, não prova de irregularidade.
4. O "custo" é o valor aprovado pelo SUS (remuneração), não o custo econômico do hospital.
5. Se a pergunta estiver fora do escopo dos dados (ex.: dados de pacientes, outros países, previsões \
sem ferramenta), explique o que os dados permitem responder.

## Formato
Responda em português do Brasil, de forma direta: primeiro a resposta em 1–2 frases, depois os números \
de apoio (tabela Markdown curta quando comparar itens) e, ao final, uma linha "Limitações:" quando relevante. \
Formate valores como R$ 1.234,56 e percentuais como 6,1%, com as mesmas casas decimais dos resultados."""


class HealthCostAgent:
    def __init__(self, fact: pd.DataFrame, *, synthetic: bool = True, client: Any = None,
                 model: str = DEFAULT_MODEL, max_steps: int = MAX_STEPS, audit_log: Path | None = None) -> None:
        if fact.empty:
            raise ValueError("A tabela fato está vazia.")
        self.fact = fact
        self.model = model
        self.max_steps = max_steps
        self.audit_log = audit_log
        self.system_prompt = build_system_prompt(fact, synthetic)
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic  # import tardio: o restante do projeto não depende do SDK

            self._client = anthropic.Anthropic()  # credenciais do ambiente (ANTHROPIC_API_KEY / ant auth)
        return self._client

    # ------------------------------------------------------------------ modelo
    def _create(self, messages: list[dict]) -> Any:
        import anthropic

        try:
            return self.client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}],
                tools=agent_tools.TOOL_SPECS,
                messages=messages,
                cache_control={"type": "ephemeral"},  # cacheia também o histórico crescente
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise AgentError("Credencial da API do Claude ausente ou inválida. Defina ANTHROPIC_API_KEY "
                             "(ou execute `ant auth login`).") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AgentError("A credencial não tem permissão para este modelo.") from exc
        except anthropic.RateLimitError as exc:
            raise AgentError("Limite de requisições atingido. Tente novamente em instantes.") from exc
        except anthropic.APIStatusError as exc:
            raise AgentError(f"Erro da API do Claude ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise AgentError("Não foi possível conectar à API do Claude. Verifique a rede.") from exc
        except TypeError as exc:
            # O SDK sinaliza ausência de credencial com TypeError ao montar os cabeçalhos.
            if "authentication" not in str(exc).lower():
                raise
            raise AgentError("Nenhuma credencial da API do Claude encontrada. Defina ANTHROPIC_API_KEY "
                             "(ou execute `ant auth login`).") from exc
        except anthropic.AnthropicError as exc:  # ex.: cliente sem credencial configurada
            raise AgentError(f"Não foi possível usar a API do Claude: {exc}. Defina ANTHROPIC_API_KEY "
                             "(ou execute `ant auth login`).") from exc

    # ------------------------------------------------------------------ ferramentas
    def _run_tool(self, block: Any) -> tuple[dict, ToolCall]:
        call = execute_tool(self.fact, block.name, block.input if isinstance(block.input, dict) else {})
        result = {"type": "tool_result", "tool_use_id": block.id, "content": tool_result_text(call)}
        if not call.ok:
            result["is_error"] = True
        return result, call

    # ------------------------------------------------------------------ loop
    def ask(self, question: str, conversation: Conversation | None = None) -> AgentResult:
        question = (question or "").strip()
        if not question:
            raise ValueError("Pergunta vazia.")
        conv = conversation if conversation is not None else Conversation()
        conv.messages.append({"role": "user", "content": question})
        calls: list[ToolCall] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        response, stop_reason, steps = None, "", 0

        while True:
            if steps >= self.max_steps:
                stop_reason = "max_steps"
                break
            steps += 1
            try:
                response = self._create(conv.messages)
            except AgentError:
                # Fecha o turno para manter a alternância de papéis (histórico somente acréscimo).
                conv.messages.append({"role": "assistant", "content": "(consulta interrompida por erro)"})
                raise
            for key in usage:
                usage[key] += int(getattr(response.usage, key, 0) or 0)
            conv.messages.append({"role": "assistant", "content": response.content})
            stop_reason = response.stop_reason

            if stop_reason == "tool_use":
                results = []
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        result, call = self._run_tool(block)
                        results.append(result)
                        calls.append(call)
                        if call.ok:
                            conv.tool_outputs.append(call.output)
                conv.messages.append({"role": "user", "content": results})  # todos os resultados juntos
                continue
            if stop_reason == "pause_turn":
                continue
            break

        answer = _text(response) if response is not None else ""
        if stop_reason == "refusal":
            answer = "O modelo recusou esta solicitação. Reformule a pergunta sobre custos hospitalares."
        elif stop_reason == "max_tokens":
            answer += "\n\n_(Resposta interrompida por limite de tamanho.)_"
        elif stop_reason == "max_steps":
            # Mantém a alternância de papéis no histórico (somente acréscimo) para o próximo turno.
            conv.messages.append({"role": "assistant", "content": "(análise interrompida por limite de etapas)"})
            answer = (answer + "\n\n" if answer else "") + (
                f"_(Interrompido após {self.max_steps} etapas. Reformule a pergunta de forma mais específica.)_")

        result = AgentResult(
            question=question, answer=answer.strip(), tool_calls=calls, steps=steps, stop_reason=stop_reason,
            model=getattr(response, "model", self.model), usage=usage,
            ungrounded=ungrounded_numbers(answer, conv.tool_outputs),
        )
        self._audit(result)
        return result

    def _audit(self, result: AgentResult) -> None:
        write_audit(self.audit_log, result)


def _text(response: Any) -> str:
    return "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def from_settings(**kwargs: Any) -> HealthCostAgent:
    """Cria o agente a partir da configuração do projeto (roda o pipeline se necessário)."""
    from hcb.config import load_settings
    from hcb.pipeline import load_fact

    settings = load_settings()
    fact = load_fact(settings)
    kwargs.setdefault("audit_log", settings.reports_dir / "agent_audit.jsonl")
    return HealthCostAgent(fact, synthetic=settings.source_type == "synthetic", **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pergunte aos dados do Health Cost Benchmark.")
    parser.add_argument("question", nargs="+", help="Pergunta em linguagem natural")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("-v", "--verbose", action="store_true", help="Mostra as chamadas de ferramenta")
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
              f"tokens_out={result.usage['output_tokens']} cache_read={result.usage['cache_read_input_tokens']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
