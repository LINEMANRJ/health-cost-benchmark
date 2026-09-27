"""Ferramentas determinísticas para um futuro agente de IA / análise conversacional.

Princípio de projeto: o modelo de linguagem NÃO calcula números — ele escolhe e chama estas
ferramentas, que executam o mesmo código auditável do pipeline e devolvem JSON. Assim, cada
resposta do agente é rastreável até uma função testada.

Nenhuma chave de API é usada aqui. Para conectar um LLM com suporte a *tool use*, exponha
`TOOL_SPECS` como definições de ferramentas e despache as chamadas com `call_tool`.
Ver docs/future_improvements.md.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from hcb.analysis import indicators, outliers, statistics


def _filter(df: pd.DataFrame, filters: dict[str, Any] | None) -> pd.DataFrame:
    allowed = {"regiao", "uf_sigla", "subgrupo_codigo", "grupo_codigo", "ano"}
    for key, value in (filters or {}).items():
        if key not in allowed:
            raise ValueError(f"Filtro não suportado: {key}. Use um de {sorted(allowed)}.")
        values = value if isinstance(value, list) else [value]
        df = df[df[key].astype(str).isin([str(v) for v in values])]
    if df.empty:
        raise ValueError("Nenhum dado para os filtros informados.")
    return df


def _records(df: pd.DataFrame, limit: int = 30) -> list[dict]:
    return df.head(limit).astype(object).where(df.head(limit).notna(), None).to_dict(orient="records")


def get_kpis(fact: pd.DataFrame, filters: dict | None = None) -> dict:
    return indicators.kpis(_filter(fact, filters))


def compare_by(fact: pd.DataFrame, dimension: str, filters: dict | None = None) -> list[dict]:
    if dimension not in {"regiao", "uf_sigla", "subgrupo_nome", "grupo_nome"}:
        raise ValueError("dimension deve ser regiao, uf_sigla, subgrupo_nome ou grupo_nome.")
    df = _filter(fact, filters)
    out = indicators.summarize(df, dimension)
    if dimension in {"regiao", "uf_sigla"}:
        out = out.merge(indicators.mix_adjusted_index(df, dimension)[[dimension, "indice_custo_ajustado"]],
                        on=dimension)
    return _records(out)


def cost_trend(fact: pd.DataFrame, filters: dict | None = None) -> dict:
    m = indicators.monthly(_filter(fact, filters)).set_index("data")["custo_medio_por_internacao"]
    return statistics.trend(m)


def list_outliers(fact: pd.DataFrame, filters: dict | None = None, z_threshold: float = 3.5) -> list[dict]:
    scored = outliers.detect_outliers(fact, z_threshold)
    return _records(outliers.outlier_table(_filter(scored, filters)))


TOOLS: dict[str, Callable[..., Any]] = {
    "get_kpis": get_kpis,
    "compare_by": compare_by,
    "cost_trend": cost_trend,
    "list_outliers": list_outliers,
}

_FILTERS_SCHEMA = {
    "type": "object",
    "description": "Filtros opcionais, ex.: {\"regiao\": \"Sul\", \"ano\": 2024}",
    "properties": {k: {"type": ["string", "integer", "array"]}
                   for k in ["regiao", "uf_sigla", "subgrupo_codigo", "grupo_codigo", "ano"]},
}

TOOL_SPECS: list[dict] = [
    {"name": "get_kpis", "description": "KPIs de custo (valor, internações, custo médio, mediana, variação 12m).",
     "input_schema": {"type": "object", "properties": {"filters": _FILTERS_SCHEMA}}},
    {"name": "compare_by", "description": "Compara indicadores por região, UF, grupo ou subgrupo.",
     "input_schema": {"type": "object", "required": ["dimension"], "properties": {
         "dimension": {"type": "string", "enum": ["regiao", "uf_sigla", "subgrupo_nome", "grupo_nome"]},
         "filters": _FILTERS_SCHEMA}}},
    {"name": "cost_trend", "description": "Tendência anual do custo médio (Theil–Sen, Mann–Kendall).",
     "input_schema": {"type": "object", "properties": {"filters": _FILTERS_SCHEMA}}},
    {"name": "list_outliers", "description": "Lista células atípicas de custo por internação.",
     "input_schema": {"type": "object", "properties": {"filters": _FILTERS_SCHEMA,
                                                       "z_threshold": {"type": "number"}}}},
]


def call_tool(fact: pd.DataFrame, name: str, arguments: dict | None = None) -> Any:
    """Despacha uma chamada de ferramenta (nome + argumentos JSON) para a função correspondente."""
    if name not in TOOLS:
        raise KeyError(f"Ferramenta desconhecida: {name}")
    return TOOLS[name](fact, **(arguments or {}))
