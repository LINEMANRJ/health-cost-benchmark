"""Ponte Python ↔ JavaScript do chat do site (executada no navegador via Pyodide).

Carrega a tabela fato e expõe ao JavaScript as MESMAS funções testadas do projeto:
ferramentas (`hcb.ai.tools`), system prompt (`hcb.ai.agent.build_system_prompt`),
formato Cohere das ferramentas e a verificação numérica (`hcb.ai.grounding`).
Nenhuma chave de API passa por aqui: as chamadas ao modelo são feitas pelo JavaScript.
"""
import json
import sys

sys.path.insert(0, "/home/pyodide/pkg")

import pandas as pd  # noqa: E402

from hcb.ai import tools as _tools  # noqa: E402
from hcb.ai.agent import build_system_prompt, execute_tool  # noqa: E402
from hcb.ai.cohere_agent import cohere_tools  # noqa: E402
from hcb.ai.grounding import ungrounded_numbers  # noqa: E402
from hcb.schema import REGION_ORDER  # noqa: E402

fact = pd.read_csv("/home/pyodide/fato.csv", dtype={"subgrupo_codigo": str, "grupo_codigo": str},
                   parse_dates=["data"])
fact["regiao"] = pd.Categorical(fact["regiao"], categories=REGION_ORDER, ordered=True)

SYSTEM_PROMPT = build_system_prompt(fact, synthetic=True)
ANTHROPIC_TOOLS = json.dumps(_tools.TOOL_SPECS, ensure_ascii=False)
COHERE_TOOLS = json.dumps(cohere_tools(), ensure_ascii=False)

_outputs: list = []


def run_tool(name: str, args_json: str) -> str:
    """Executa uma ferramenta e devolve JSON {ok, output, error, duration_ms}."""
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        args = {"__argumentos_invalidos__": args_json[:200]}
    if not isinstance(args, dict):
        args = {}
    call = execute_tool(fact, name, args)
    if call.ok:
        _outputs.append(call.output)
    return json.dumps({"ok": call.ok, "output": call.output, "error": call.error,
                       "duration_ms": call.duration_ms}, ensure_ascii=False, default=str)


def check_answer(answer: str) -> str:
    """Números da resposta sem correspondência nas saídas de ferramenta desta conversa."""
    return json.dumps(ungrounded_numbers(answer, _outputs), ensure_ascii=False)


def reset() -> None:
    _outputs.clear()
