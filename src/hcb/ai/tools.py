"""Ferramentas determinísticas usadas pelo agente de IA (hcb.ai.agent).

Princípio de projeto: o modelo de linguagem NÃO calcula números. Ele escolhe e chama estas
ferramentas, que executam o mesmo código testado do pipeline e devolvem JSON. Assim, cada
número de uma resposta é rastreável até uma função testada (e verificável pelo módulo
`hcb.ai.grounding`).

Todas as ferramentas são somente leitura, validam a entrada e devolvem estruturas pequenas
(limites de linhas) para não inflar o contexto do modelo.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from hcb.analysis import indicators, outliers, statistics

FILTER_KEYS = {"regiao", "uf_sigla", "grupo_codigo", "subgrupo_codigo", "ano", "competencia_inicio",
               "competencia_fim"}
DIMENSIONS = {"regiao", "uf_sigla", "grupo_nome", "subgrupo_nome"}
MAX_ROWS = 30


class ToolInputError(ValueError):
    """Entrada inválida para uma ferramenta (devolvida ao modelo como erro, não como exceção fatal)."""


# --------------------------------------------------------------------------- utilidades
def _clean(obj: Any) -> Any:
    """Converte para tipos JSON e arredonda floats (dinheiro: 2 casas; razões: 4 casas)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        if math.isnan(x) or math.isinf(x):
            return None
        return round(x, 2) if abs(x) >= 100 else round(x, 4)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m")
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _records(df: pd.DataFrame, limit: int = MAX_ROWS) -> list[dict]:
    return _clean(df.head(limit).to_dict(orient="records"))


def _period(value: Any, name: str) -> str:
    text = str(value)
    if len(text) != 7 or text[4] != "-" or not (text[:4] + text[5:]).isdigit():
        raise ToolInputError(f"{name} deve estar no formato AAAA-MM (recebido: {value!r}).")
    return text


def _filter(df: pd.DataFrame, filters: dict[str, Any] | None) -> pd.DataFrame:
    filters = filters or {}
    if not isinstance(filters, dict):
        raise ToolInputError("filters deve ser um objeto, ex.: {\"regiao\": \"Sul\"}.")
    for key, value in filters.items():
        if key not in FILTER_KEYS:
            raise ToolInputError(f"Filtro não suportado: {key}. Use um de {sorted(FILTER_KEYS)}.")
        if key == "competencia_inicio":
            df = df[df["competencia"] >= _period(value, key)]
        elif key == "competencia_fim":
            df = df[df["competencia"] <= _period(value, key)]
        else:
            values = value if isinstance(value, list) else [value]
            df = df[df[key].astype(str).isin([str(v) for v in values])]
    if df.empty:
        raise ToolInputError("Nenhum dado para os filtros informados. Use list_dimensions para ver valores válidos.")
    return df


# --------------------------------------------------------------------------- ferramentas
def list_dimensions(fact: pd.DataFrame) -> dict:
    sg = fact[["grupo_codigo", "grupo_nome", "subgrupo_codigo", "subgrupo_nome"]].drop_duplicates()
    return {
        "periodo": {"inicio": fact["competencia"].min(), "fim": fact["competencia"].max(),
                    "meses": int(fact["competencia"].nunique())},
        "regioes": [str(r) for r in fact["regiao"].dropna().unique()],
        "ufs": sorted(fact["uf_sigla"].unique().tolist()),
        "anos": sorted(int(a) for a in fact["ano"].unique()),
        "subgrupos": _records(sg.sort_values("subgrupo_codigo"), limit=100),
    }


def get_kpis(fact: pd.DataFrame, filters: dict | None = None) -> dict:
    return _clean(indicators.kpis(_filter(fact, filters)))


def compare_by(fact: pd.DataFrame, dimension: str, filters: dict | None = None,
               order_by: str = "valor_total", limit: int = MAX_ROWS) -> list[dict]:
    if dimension not in DIMENSIONS:
        raise ToolInputError(f"dimension deve ser um de {sorted(DIMENSIONS)}.")
    df = _filter(fact, filters)
    out = indicators.summarize(df, dimension)
    if dimension in {"regiao", "uf_sigla"}:
        out = out.merge(indicators.mix_adjusted_index(df, dimension)[[dimension, "indice_custo_ajustado"]],
                        on=dimension)
        out = out.merge(indicators.utilization_rate(df, dimension), on=dimension)
    if order_by not in out.columns:
        raise ToolInputError(f"order_by inválido. Opções: {sorted(c for c in out.columns if c != dimension)}.")
    cols = [dimension, "valor_total", "participacao_valor", "internacoes", "custo_medio_por_internacao",
            "custo_mediano_celula", "custo_por_dia", "permanencia_media"]
    cols += [c for c in ("indice_custo_ajustado", "internacoes_por_10mil_hab_mes") if c in out.columns]
    return _records(out.sort_values(order_by, ascending=False)[cols], limit=min(int(limit), MAX_ROWS))


def cost_trend(fact: pd.DataFrame, filters: dict | None = None) -> dict:
    m = indicators.monthly(_filter(fact, filters)).set_index("data")["custo_medio_por_internacao"]
    return _clean({**statistics.trend(m), "metodo": "Theil-Sen sobre log do custo médio mensal; Mann-Kendall"})


def monthly_series(fact: pd.DataFrame, filters: dict | None = None, by: str | None = None) -> list[dict]:
    if by not in (None, "regiao"):
        raise ToolInputError("by aceita apenas 'regiao' ou nulo.")
    m = indicators.monthly(_filter(fact, filters), by)
    cols = ["data"] + ([by] if by else []) + ["valor_total", "internacoes", "custo_medio_por_internacao",
                                              "variacao_12m"]
    return _records(m[cols], limit=200)


def variation_between_ufs(fact: pd.DataFrame, filters: dict | None = None) -> list[dict]:
    return _records(statistics.variation_between_ufs(_filter(fact, filters)))


def regional_differences(fact: pd.DataFrame, filters: dict | None = None) -> list[dict]:
    cols = ["subgrupo_nome", "ufs", "epsilon2", "magnitude_efeito", "p_ajustado_holm", "diferenca_significativa",
            "regiao_maior_mediana", "regiao_menor_mediana", "razao_max_min_mediana"]
    return _records(statistics.regional_differences(_filter(fact, filters))[cols])


def concentration(fact: pd.DataFrame, dimension: str = "subgrupo_nome", filters: dict | None = None) -> dict:
    if dimension not in DIMENSIONS:
        raise ToolInputError(f"dimension deve ser um de {sorted(DIMENSIONS)}.")
    table, summary = indicators.concentration(_filter(fact, filters), dimension)
    return {"resumo": _clean(summary), "itens": _records(table)}


def list_outliers(fact: pd.DataFrame, filters: dict | None = None, z_threshold: float = 3.5,
                  limit: int = 15) -> dict:
    if not 2.0 <= float(z_threshold) <= 10.0:
        raise ToolInputError("z_threshold deve estar entre 2 e 10.")
    scored = outliers.detect_outliers(fact, float(z_threshold))  # modelo usa o conjunto completo
    table = outliers.outlier_table(_filter(scored, filters))
    above = table[table["z_robusto"] > 0]
    return {
        "total_atipicos": int(len(table)),
        "acima_do_esperado": int(len(above)),
        "excesso_estimado_total": _clean(float(above["excesso_estimado"].sum())),
        "maiores": _records(table, limit=min(int(limit), MAX_ROWS)),
        "aviso": "Atipicidade indica prioridade de verificação; não comprova erro, fraude ou ineficiência.",
    }


def compare_periods(fact: pd.DataFrame, periodo_a: dict, periodo_b: dict, filters: dict | None = None,
                    by: str | None = None) -> dict:
    """Compara dois períodos e decompõe a variação do valor total em volume, mix e preço.

    ΔV = efeito volume + efeito mix + efeito custo unitário, com a identidade exata:
      volume = (Q_b − Q_a) × P_a
      mix    = Q_b × (Σ w_b,s × p_a,s − P_a)
      custo  = Q_b × Σ w_b,s × (p_b,s − p_a,s)
    onde s = subgrupo, Q = internações, w = participação no volume, p = custo médio, P = custo médio geral.
    """
    if by not in (None, "regiao", "uf_sigla"):
        raise ToolInputError("by aceita 'regiao', 'uf_sigla' ou nulo.")
    base = _filter(fact, filters)

    def window(p: dict, name: str) -> pd.DataFrame:
        if not isinstance(p, dict) or "inicio" not in p or "fim" not in p:
            raise ToolInputError(f"{name} deve ser {{\"inicio\": \"AAAA-MM\", \"fim\": \"AAAA-MM\"}}.")
        a, b = _period(p["inicio"], f"{name}.inicio"), _period(p["fim"], f"{name}.fim")
        w = base[base["competencia"].between(a, b)]
        if w.empty:
            raise ToolInputError(f"Sem dados em {name} ({a} a {b}).")
        return w

    a, b = window(periodo_a, "periodo_a"), window(periodo_b, "periodo_b")

    def decompose(da: pd.DataFrame, db: pd.DataFrame) -> dict:
        sa = da.groupby("subgrupo_codigo")[["valor_total", "qtd_internacoes"]].sum()
        sb = db.groupby("subgrupo_codigo")[["valor_total", "qtd_internacoes"]].sum()
        qa, qb = sa["qtd_internacoes"].sum(), sb["qtd_internacoes"].sum()
        va, vb = sa["valor_total"].sum(), sb["valor_total"].sum()
        pa_all = va / qa
        pa = (sa["valor_total"] / sa["qtd_internacoes"]).reindex(sb.index)
        pb = sb["valor_total"] / sb["qtd_internacoes"]
        pa = pa.fillna(pb)  # subgrupo ausente no período A: sem efeito de custo unitário
        wb = sb["qtd_internacoes"] / qb
        volume = (qb - qa) * pa_all
        mix = qb * ((wb * pa).sum() - pa_all)
        custo = qb * (wb * (pb - pa)).sum()
        return {
            "valor_a": va, "valor_b": vb, "variacao_valor": vb - va, "variacao_valor_pct": vb / va - 1,
            "internacoes_a": qa, "internacoes_b": qb, "variacao_internacoes_pct": qb / qa - 1,
            "custo_medio_a": pa_all, "custo_medio_b": vb / qb, "variacao_custo_medio_pct": (vb / qb) / pa_all - 1,
            "efeito_volume": volume, "efeito_mix": mix, "efeito_custo_unitario": custo,
        }

    result = {"periodo_a": periodo_a, "periodo_b": periodo_b, "total": decompose(a, b),
              "nota": "Valores nominais. Efeitos somam a variação total (identidade exata). "
                      "Meses diferentes podem ter sazonalidade distinta: compare janelas equivalentes."}
    if by:
        parts = []
        for key in sorted(set(a[by].astype(str)) & set(b[by].astype(str))):
            d = decompose(a[a[by].astype(str) == key], b[b[by].astype(str) == key])
            parts.append({by: key, **d})
        parts.sort(key=lambda r: r["variacao_valor"], reverse=True)
        result["por_" + by] = parts[:MAX_ROWS]
    return _clean(result)


# --------------------------------------------------------------------------- registro
TOOLS: dict[str, Callable[..., Any]] = {
    "list_dimensions": list_dimensions,
    "get_kpis": get_kpis,
    "compare_by": compare_by,
    "cost_trend": cost_trend,
    "monthly_series": monthly_series,
    "variation_between_ufs": variation_between_ufs,
    "regional_differences": regional_differences,
    "concentration": concentration,
    "list_outliers": list_outliers,
    "compare_periods": compare_periods,
}

_FILTERS_SCHEMA = {
    "type": "object",
    "description": ("Filtros opcionais combináveis. Valores válidos via list_dimensions. "
                    "Ex.: {\"regiao\": \"Sul\", \"subgrupo_codigo\": \"0406\", \"competencia_inicio\": \"2024-01\"}"),
    "properties": {
        "regiao": {"type": ["string", "array"], "description": "Norte, Nordeste, Centro-Oeste, Sudeste ou Sul"},
        "uf_sigla": {"type": ["string", "array"], "description": "Sigla da UF, ex.: SP"},
        "grupo_codigo": {"type": ["string", "array"], "description": "Grupo SIGTAP: 03, 04 ou 05"},
        "subgrupo_codigo": {"type": ["string", "array"], "description": "Subgrupo SIGTAP (4 dígitos)"},
        "ano": {"type": ["integer", "array"]},
        "competencia_inicio": {"type": "string", "description": "AAAA-MM (inclusive)"},
        "competencia_fim": {"type": "string", "description": "AAAA-MM (inclusive)"},
    },
    "additionalProperties": False,
}
_PERIOD_SCHEMA = {
    "type": "object",
    "properties": {"inicio": {"type": "string", "description": "AAAA-MM"},
                   "fim": {"type": "string", "description": "AAAA-MM"}},
    "required": ["inicio", "fim"],
    "additionalProperties": False,
}


def _spec(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "input_schema": schema}


TOOL_SPECS: list[dict] = [
    _spec("list_dimensions",
          "Lista o período disponível e os valores válidos de região, UF, ano, grupo e subgrupo SIGTAP. "
          "Use antes de filtrar quando não tiver certeza de um código ou nome."),
    _spec("get_kpis",
          "KPIs do recorte: valor total, internações, custo médio por internação (ponderado), medianas, "
          "custo por dia, permanência média e variação dos últimos 12 meses vs. 12 anteriores.",
          {"filters": _FILTERS_SCHEMA}),
    _spec("compare_by",
          "Ranking de indicadores por dimensão (regiao, uf_sigla, grupo_nome, subgrupo_nome). Para regiao/uf_sigla "
          "inclui índice de custo ajustado ao mix (1 = esperado para o mix de procedimentos) e taxa de utilização.",
          {"dimension": {"type": "string", "enum": sorted(DIMENSIONS)},
           "filters": _FILTERS_SCHEMA,
           "order_by": {"type": "string", "description": "Coluna de ordenação (padrão valor_total), ex.: "
                                                         "indice_custo_ajustado, custo_medio_por_internacao"},
           "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}},
          ["dimension"]),
    _spec("cost_trend",
          "Tendência anual do custo médio por internação no recorte (Theil-Sen com IC95% e teste de Mann-Kendall).",
          {"filters": _FILTERS_SCHEMA}),
    _spec("monthly_series",
          "Série mensal de valor, internações, custo médio e variação vs. mesmo mês do ano anterior.",
          {"filters": _FILTERS_SCHEMA, "by": {"type": "string", "enum": ["regiao"]}}),
    _spec("variation_between_ufs",
          "Dispersão do custo médio entre UFs por subgrupo (CV, razão P90/P10, UFs de menor e maior custo).",
          {"filters": _FILTERS_SCHEMA}),
    _spec("regional_differences",
          "Teste de Kruskal-Wallis por subgrupo: o custo difere entre regiões? Tamanho de efeito (épsilon²) e p "
          "ajustado por Holm. Resultado é associação, não causalidade.",
          {"filters": _FILTERS_SCHEMA}),
    _spec("concentration",
          "Participação no valor total, curva de Pareto (80%) e índice HHI por dimensão.",
          {"dimension": {"type": "string", "enum": sorted(DIMENSIONS)}, "filters": _FILTERS_SCHEMA}),
    _spec("list_outliers",
          "Células (competência × UF × subgrupo) com custo por internação atípico em relação ao esperado, com "
          "excesso estimado. Sinal para auditoria, não prova de irregularidade.",
          {"filters": _FILTERS_SCHEMA,
           "z_threshold": {"type": "number", "minimum": 2, "maximum": 10, "description": "Padrão 3,5"},
           "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}}),
    _spec("compare_periods",
          "Compara dois períodos e decompõe a variação do valor total em efeito volume, efeito mix de "
          "procedimentos e efeito custo unitário (soma exata). Opcionalmente detalha por regiao ou uf_sigla. "
          "Use para perguntas do tipo 'o que explica o aumento do gasto'.",
          {"periodo_a": _PERIOD_SCHEMA, "periodo_b": _PERIOD_SCHEMA, "filters": _FILTERS_SCHEMA,
           "by": {"type": "string", "enum": ["regiao", "uf_sigla"]}},
          ["periodo_a", "periodo_b"]),
]


def call_tool(fact: pd.DataFrame, name: str, arguments: dict | None = None) -> Any:
    """Despacha uma chamada de ferramenta (nome + argumentos JSON) para a função correspondente."""
    if name not in TOOLS:
        raise KeyError(f"Ferramenta desconhecida: {name}")
    arguments = arguments or {}
    if not isinstance(arguments, dict):
        raise ToolInputError("Os argumentos devem ser um objeto JSON.")
    try:
        return TOOLS[name](fact, **arguments)
    except TypeError as exc:  # argumento inesperado ou ausente
        raise ToolInputError(f"Argumentos inválidos para {name}: {exc}") from exc
