"""Análises estatísticas: tendência, variabilidade e diferenças regionais.

Os testes descrevem associações nos dados agregados. Nenhum resultado aqui deve ser
lido como relação causal (ver docs/methodology.md, seção "Limites de interpretação").
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

MIN_POINTS_TREND = 12


def holm_adjust(pvalues: pd.Series) -> pd.Series:
    """Correção de Holm-Bonferroni para comparações múltiplas."""
    p = pvalues.astype(float)
    valid = p.dropna().sort_values()
    m = len(valid)
    adjusted = pd.Series(np.nan, index=p.index, dtype=float)
    running = 0.0
    for rank, (idx, value) in enumerate(valid.items()):
        running = max(running, min(1.0, (m - rank) * value))
        adjusted[idx] = running
    return adjusted


def trend(series: pd.Series) -> dict[str, float]:
    """Tendência monotônica de uma série mensal positiva.

    - Inclinação de Theil–Sen sobre log(série) → crescimento anual composto (robusto a outliers).
    - Teste de Mann–Kendall (tau de Kendall contra o tempo) para significância.
    """
    y = series.dropna()
    y = y[y > 0]
    if len(y) < MIN_POINTS_TREND:
        return {"n_meses": len(y), "crescimento_anual": np.nan, "ic95_inf": np.nan,
                "ic95_sup": np.nan, "tau_kendall": np.nan, "p_valor": np.nan}
    t = np.arange(len(y))
    logy = np.log(y.to_numpy())
    slope, _, lo, hi = stats.theilslopes(logy, t, alpha=0.95)
    tau, p = stats.kendalltau(t, logy)
    return {
        "n_meses": int(len(y)),
        "crescimento_anual": float(np.expm1(slope * 12)),
        "ic95_inf": float(np.expm1(lo * 12)),
        "ic95_sup": float(np.expm1(hi * 12)),
        "tau_kendall": float(tau),
        "p_valor": float(p),
    }


def trends_by(df: pd.DataFrame, by: str, alpha: float = 0.05) -> pd.DataFrame:
    """Tendência do custo médio por internação para cada categoria de `by`."""
    rows = []
    for key, part in df.groupby(by, observed=True):
        m = part.groupby("data")[["valor_total", "qtd_internacoes"]].sum()
        rows.append({by: key, **trend(m["valor_total"] / m["qtd_internacoes"])})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["p_ajustado_holm"] = holm_adjust(out["p_valor"])
    out["tendencia"] = np.select(
        [(out["p_ajustado_holm"] < alpha) & (out["crescimento_anual"] > 0),
         (out["p_ajustado_holm"] < alpha) & (out["crescimento_anual"] < 0)],
        ["alta", "queda"], default="sem tendência significativa",
    )
    return out.sort_values("crescimento_anual", ascending=False).reset_index(drop=True)


def variation_between_ufs(df: pd.DataFrame, min_admissions: int = 30) -> pd.DataFrame:
    """Dispersão do custo médio por internação entre UFs, por subgrupo.

    Unidade de análise: UF no período inteiro (custo = Σvalor/Σinternações), apenas UFs
    com pelo menos `min_admissions` internações no subgrupo, para evitar instabilidade
    de pequenos números.
    """
    uf = df.groupby(["subgrupo_codigo", "subgrupo_nome", "uf_sigla"], observed=True)[
        ["valor_total", "qtd_internacoes"]
    ].sum().reset_index()
    uf = uf[uf["qtd_internacoes"] >= min_admissions]
    uf["custo"] = uf["valor_total"] / uf["qtd_internacoes"]

    def describe(g: pd.DataFrame) -> pd.Series:
        c = g["custo"]
        return pd.Series({
            "ufs_avaliadas": int(len(c)),
            "custo_mediano_ufs": c.median(),
            "cv_entre_ufs": c.std(ddof=1) / c.mean() if len(c) > 1 else np.nan,
            "razao_p90_p10": c.quantile(0.9) / c.quantile(0.1) if len(c) > 2 else np.nan,
            "uf_menor_custo": g.loc[c.idxmin(), "uf_sigla"],
            "uf_maior_custo": g.loc[c.idxmax(), "uf_sigla"],
            "menor_custo": c.min(),
            "maior_custo": c.max(),
        })

    out = uf.groupby(["subgrupo_codigo", "subgrupo_nome"]).apply(describe, include_groups=False).reset_index()
    return out.sort_values("cv_entre_ufs", ascending=False).reset_index(drop=True)


def regional_differences(df: pd.DataFrame, alpha: float = 0.05, min_admissions: int = 30) -> pd.DataFrame:
    """Teste de Kruskal–Wallis: o custo médio por internação das UFs difere entre regiões?

    Executado por subgrupo (controla parcialmente o mix de procedimentos). Unidade = UF
    no período (evita pseudo-replicação de meses correlacionados). Tamanho de efeito:
    épsilon² = H / (n − 1). p-valores ajustados por Holm entre subgrupos.
    """
    uf = df.groupby(["subgrupo_codigo", "subgrupo_nome", "regiao", "uf_sigla"], observed=True)[
        ["valor_total", "qtd_internacoes"]
    ].sum().reset_index()
    uf = uf[uf["qtd_internacoes"] >= min_admissions]
    uf["custo"] = uf["valor_total"] / uf["qtd_internacoes"]

    rows = []
    for (code, name), g in uf.groupby(["subgrupo_codigo", "subgrupo_nome"]):
        groups = [s["custo"].to_numpy() for _, s in g.groupby("regiao", observed=True) if len(s) >= 2]
        medians = g.groupby("regiao", observed=True)["custo"].median()
        row = {"subgrupo_codigo": code, "subgrupo_nome": name, "ufs": len(g), "regioes": len(groups),
               "regiao_maior_mediana": medians.idxmax(), "regiao_menor_mediana": medians.idxmin(),
               "razao_max_min_mediana": medians.max() / medians.min()}
        if len(groups) >= 2:
            h, p = stats.kruskal(*groups)
            n = sum(len(x) for x in groups)
            row.update({"h": float(h), "p_valor": float(p), "epsilon2": float(h / (n - 1))})
        else:
            row.update({"h": np.nan, "p_valor": np.nan, "epsilon2": np.nan})
        rows.append(row)

    out = pd.DataFrame(rows)
    out["p_ajustado_holm"] = holm_adjust(out["p_valor"])
    out["diferenca_significativa"] = out["p_ajustado_holm"] < alpha
    out["magnitude_efeito"] = pd.cut(
        out["epsilon2"], bins=[-np.inf, 0.01, 0.08, 0.26, np.inf],
        labels=["desprezível", "pequeno", "moderado", "grande"],
    ).astype(str)
    return out.sort_values("epsilon2", ascending=False).reset_index(drop=True)


def spearman_volume_cost(df: pd.DataFrame, min_admissions: int = 30) -> pd.DataFrame:
    """Correlação de Spearman entre volume e custo médio das UFs, por subgrupo.

    Descreve associação (ex.: escala), NÃO efeito causal do volume sobre o custo.
    """
    uf = df.groupby(["subgrupo_codigo", "subgrupo_nome", "uf_sigla"], observed=True)[
        ["valor_total", "qtd_internacoes"]
    ].sum().reset_index()
    uf = uf[uf["qtd_internacoes"] >= min_admissions]
    rows = []
    for (code, name), g in uf.groupby(["subgrupo_codigo", "subgrupo_nome"]):
        if len(g) < 5:
            continue
        rho, p = stats.spearmanr(g["qtd_internacoes"], g["valor_total"] / g["qtd_internacoes"])
        rows.append({"subgrupo_codigo": code, "subgrupo_nome": name, "ufs": len(g),
                     "rho_spearman": float(rho), "p_valor": float(p)})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["p_ajustado_holm"] = holm_adjust(out["p_valor"])
    return out
