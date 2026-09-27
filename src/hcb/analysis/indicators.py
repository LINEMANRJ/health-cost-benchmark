"""Indicadores de custo e economicidade.

Todas as funções recebem a tabela fato (1 linha = competência × UF × subgrupo) e
são puras, para serem reutilizadas pelo pipeline, notebooks e dashboard (que
recalcula os indicadores sobre o recorte filtrado). Metodologia: docs/methodology.md.
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def weighted_quantile(values: Iterable[float], weights: Iterable[float], q: float) -> float:
    """Quantil ponderado (interpolação sobre a distribuição acumulada dos pesos)."""
    v = np.asarray(list(values), dtype=float)
    w = np.asarray(list(weights), dtype=float)
    mask = ~np.isnan(v) & ~np.isnan(w) & (w > 0)
    v, w = v[mask], w[mask]
    if v.size == 0:
        return float("nan")
    order = np.argsort(v)
    v, w = v[order], w[order]
    cum = np.cumsum(w) - 0.5 * w
    cum /= w.sum()
    return float(np.interp(q, cum, v))


def safe_ratio(num: float, den: float) -> float:
    return float(num) / float(den) if den and not np.isnan(den) else float("nan")


def kpis(df: pd.DataFrame) -> dict[str, float | int | str]:
    """KPIs principais do recorte."""
    if df.empty:
        return {"linhas": 0}
    total_value = df["valor_total"].sum()
    total_qtd = df["qtd_internacoes"].sum()
    total_days = df["dias_permanencia"].sum()
    months = df["competencia"].nunique()
    result: dict[str, float | int | str] = {
        "linhas": int(len(df)),
        "periodo_inicio": str(df["competencia"].min()),
        "periodo_fim": str(df["competencia"].max()),
        "meses": int(months),
        "valor_total": float(total_value),
        "internacoes": int(total_qtd),
        "custo_medio_por_internacao": safe_ratio(total_value, total_qtd),
        "custo_mediano_celula": float(df["custo_por_internacao"].median()),
        "custo_mediano_ponderado": weighted_quantile(df["custo_por_internacao"], df["qtd_internacoes"], 0.5),
        "custo_por_dia": safe_ratio(total_value, total_days),
        "permanencia_media": safe_ratio(total_days, total_qtd),
        "valor_medio_mensal": safe_ratio(total_value, months),
    }
    result.update(yoy_change(df))
    return result


def yoy_change(df: pd.DataFrame) -> dict[str, float]:
    """Variação dos últimos 12 meses contra os 12 meses anteriores (exige ≥ 24 meses)."""
    months = sorted(df["competencia"].unique())
    if len(months) < 24:
        return {"variacao_12m_custo_medio": float("nan"), "variacao_12m_valor_total": float("nan"),
                "variacao_12m_internacoes": float("nan")}
    last, prev = months[-12:], months[-24:-12]
    cur = df[df["competencia"].isin(last)]
    old = df[df["competencia"].isin(prev)]
    cost_cur = safe_ratio(cur["valor_total"].sum(), cur["qtd_internacoes"].sum())
    cost_old = safe_ratio(old["valor_total"].sum(), old["qtd_internacoes"].sum())
    return {
        "variacao_12m_custo_medio": cost_cur / cost_old - 1,
        "variacao_12m_valor_total": safe_ratio(cur["valor_total"].sum(), old["valor_total"].sum()) - 1,
        "variacao_12m_internacoes": safe_ratio(cur["qtd_internacoes"].sum(), old["qtd_internacoes"].sum()) - 1,
    }


def summarize(df: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    """Indicadores agregados por dimensão (região, UF, subgrupo...)."""
    by = [by] if isinstance(by, str) else list(by)
    grouped = df.groupby(by, observed=True)
    out = grouped.agg(
        valor_total=("valor_total", "sum"),
        internacoes=("qtd_internacoes", "sum"),
        dias=("dias_permanencia", "sum"),
        celulas=("custo_por_internacao", "size"),
        custo_mediano_celula=("custo_por_internacao", "median"),
        p10=("custo_por_internacao", lambda s: s.quantile(0.10)),
        p25=("custo_por_internacao", lambda s: s.quantile(0.25)),
        p75=("custo_por_internacao", lambda s: s.quantile(0.75)),
        p90=("custo_por_internacao", lambda s: s.quantile(0.90)),
    )
    out["custo_medio_por_internacao"] = out["valor_total"] / out["internacoes"]
    out["custo_por_dia"] = out["valor_total"] / out["dias"].where(out["dias"] > 0)
    out["permanencia_media"] = out["dias"] / out["internacoes"]
    out["participacao_valor"] = out["valor_total"] / out["valor_total"].sum()
    out["amplitude_interquartil_rel"] = (out["p75"] - out["p25"]) / out["custo_mediano_celula"]
    return out.reset_index().sort_values("valor_total", ascending=False).reset_index(drop=True)


def utilization_rate(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Internações por 10 mil habitantes por mês, por UF ou região (população do Censo 2022)."""
    months = df["competencia"].nunique()
    cols = list(dict.fromkeys(["uf_sigla", by, "populacao"]))
    pop = df[cols].drop_duplicates("uf_sigla").groupby(by, observed=True)["populacao"].sum()
    qtd = df.groupby(by, observed=True)["qtd_internacoes"].sum()
    rate = (qtd / (pop * months) * 10_000).rename("internacoes_por_10mil_hab_mes")
    return rate.reset_index()


def mix_adjusted_index(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Índice de Custo Ajustado ao Mix (padronização indireta).

    Para cada unidade (UF/região): custo esperado = Σ_subgrupo internações_unidade ×
    custo médio nacional do subgrupo no mesmo mês. Índice = custo observado / esperado.
    Índice 1,10 = custo 10% acima do esperado dado o seu mix de procedimentos e período.
    """
    ref = df.groupby(["competencia", "subgrupo_codigo"], observed=True)[["valor_total", "qtd_internacoes"]].sum()
    ref = (ref["valor_total"] / ref["qtd_internacoes"]).rename("custo_ref").reset_index()
    tmp = df.merge(ref, on=["competencia", "subgrupo_codigo"], how="left")
    tmp["esperado"] = tmp["qtd_internacoes"] * tmp["custo_ref"]
    out = tmp.groupby(by, observed=True).agg(observado=("valor_total", "sum"), esperado=("esperado", "sum"))
    out["indice_custo_ajustado"] = out["observado"] / out["esperado"]
    out["diferenca_vs_esperado"] = out["observado"] - out["esperado"]
    return out.reset_index().sort_values("indice_custo_ajustado", ascending=False).reset_index(drop=True)


def monthly(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Série mensal (total ou por dimensão) com média móvel de 3 meses e variação anual."""
    keys = ["data"] + ([by] if by else [])
    out = df.groupby(keys, observed=True).agg(
        valor_total=("valor_total", "sum"), internacoes=("qtd_internacoes", "sum")
    ).reset_index()
    out["custo_medio_por_internacao"] = out["valor_total"] / out["internacoes"]
    grp = out.groupby(by, observed=True) if by else None
    col = "custo_medio_por_internacao"
    if grp is not None:
        out["media_movel_3m"] = grp[col].transform(lambda s: s.rolling(3, min_periods=1).mean())
        out["variacao_12m"] = grp[col].transform(lambda s: s.pct_change(12))
    else:
        out["media_movel_3m"] = out[col].rolling(3, min_periods=1).mean()
        out["variacao_12m"] = out[col].pct_change(12)
    return out


def concentration(df: pd.DataFrame, by: str, pareto_share: float = 0.80) -> tuple[pd.DataFrame, dict]:
    """Participação no valor total, curva de Pareto e índice de Herfindahl-Hirschman (HHI)."""
    share = df.groupby(by, observed=True)["valor_total"].sum().sort_values(ascending=False)
    table = share.rename("valor_total").to_frame()
    table["participacao"] = table["valor_total"] / table["valor_total"].sum()
    table["participacao_acumulada"] = table["participacao"].cumsum()
    table["nucleo_pareto"] = table["participacao_acumulada"].shift(fill_value=0) < pareto_share
    hhi = float((table["participacao"] ** 2).sum() * 10_000)
    summary = {
        "dimensao": by,
        "itens": int(len(table)),
        "itens_para_participacao_alvo": int(table["nucleo_pareto"].sum()),
        "participacao_alvo": pareto_share,
        "hhi": round(hhi, 1),
        "top1_participacao": float(table["participacao"].iloc[0]) if len(table) else float("nan"),
    }
    return table.reset_index(), summary
