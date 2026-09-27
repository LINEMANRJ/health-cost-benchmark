"""Identificação de valores atípicos no custo por internação.

Método principal — escore robusto ajustado ao contexto e à precisão:

1. Resíduo em escala log: r = log(custo_célula) − [mediana_log(subgrupo, UF)
   + (mediana_log(subgrupo, mês) − mediana_log(subgrupo))]. Ou seja, compara a célula
   com o esperado para o mesmo subgrupo e UF, corrigido pelo nível nacional do mês
   (reajustes, sazonalidade).
2. Variância esperada do resíduo: Var(r) ≈ a / n + b — componente amostral (média de
   n internações) mais sobredispersão (b), estimados por mínimos quadrados em r²,
   excluindo iterativamente células com |z| > 4 (para que atípicos não inflem a variância).
   É a lógica dos funnel plots com sobredispersão
   (Spiegelhalter, 2005), que evita sinalizar células pequenas só por ruído.
3. z = r / sqrt(a/n + b), reescalado pela MAD (mediana |z| ≈ 0,6745 sob normalidade).
   |z| > limiar (padrão 3,5; Iglewicz & Hoaglin, 1993) → atípico.

Método de referência — cercas de Tukey (1,5 × IQR) sobre log(custo) dentro do subgrupo,
exibido no box plot. Atipicidade é um sinal para investigação, não prova de erro ou fraude.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _fit_variance(r: np.ndarray, n: np.ndarray, iterations: int = 5, cut: float = 4.0) -> tuple[float, float]:
    """Ajusta Var(r) = a/n + b por mínimos quadrados em r², excluindo iterativamente
    as células com |z| > `cut` para que atípicos não inflem a variância estimada."""
    keep = np.ones_like(r, dtype=bool)
    a, b = 1e-6, 1e-6
    for _ in range(iterations):
        x = np.column_stack([1.0 / n[keep], np.ones(keep.sum())])
        coef, *_ = np.linalg.lstsq(x, r[keep] ** 2, rcond=None)
        a, b = max(float(coef[0]), 1e-6), max(float(coef[1]), 1e-6)
        new_keep = np.abs(r / np.sqrt(a / n + b)) <= cut
        if (new_keep == keep).all():
            break
        keep = new_keep
    return a, b


def detect_outliers(df: pd.DataFrame, z_threshold: float = 3.5, min_admissions: int = 5) -> pd.DataFrame:
    """Adiciona colunas de atipicidade à tabela fato (retorna cópia)."""
    out = df.copy()
    out["log_custo"] = np.log(out["custo_por_internacao"].where(out["custo_por_internacao"] > 0))
    sg = out.groupby("subgrupo_codigo")["log_custo"]
    out["_med_sg"] = sg.transform("median")
    out["_med_sg_uf"] = out.groupby(["subgrupo_codigo", "uf_sigla"])["log_custo"].transform("median")
    out["_med_sg_mes"] = out.groupby(["subgrupo_codigo", "competencia"])["log_custo"].transform("median")
    out["residuo_log"] = out["log_custo"] - (out["_med_sg_uf"] + out["_med_sg_mes"] - out["_med_sg"])
    out["custo_esperado"] = np.exp(out["log_custo"] - out["residuo_log"])

    out["z_robusto"] = np.nan
    eligible = out["qtd_internacoes"] >= min_admissions
    for _, idx in out[eligible & out["residuo_log"].notna()].groupby("subgrupo_codigo").groups.items():
        part = out.loc[idx]
        if len(part) < 10:
            continue
        r = part["residuo_log"].to_numpy()
        n = part["qtd_internacoes"].to_numpy(dtype=float)
        a, b = _fit_variance(r, n)
        z = r / np.sqrt(a / n + b)
        mad = np.median(np.abs(z - np.median(z)))
        if mad > 0:
            z = 0.6745 * (z - np.median(z)) / mad
        out.loc[idx, "z_robusto"] = z

    out["atipico"] = out["z_robusto"].abs() > z_threshold
    out["direcao_atipicidade"] = np.select(
        [out["atipico"] & (out["z_robusto"] > 0), out["atipico"] & (out["z_robusto"] < 0)],
        ["acima do esperado", "abaixo do esperado"], default="",
    )
    q1 = sg.transform(lambda s: s.quantile(0.25))
    q3 = sg.transform(lambda s: s.quantile(0.75))
    iqr = q3 - q1
    out["atipico_iqr"] = (out["log_custo"] < q1 - 1.5 * iqr) | (out["log_custo"] > q3 + 1.5 * iqr)
    out["excesso_estimado"] = np.where(
        out["direcao_atipicidade"] == "acima do esperado",
        out["valor_total"] - out["custo_esperado"] * out["qtd_internacoes"], 0.0,
    )
    return out.drop(columns=["_med_sg", "_med_sg_uf", "_med_sg_mes"])


def outlier_table(scored: pd.DataFrame) -> pd.DataFrame:
    cols = ["competencia", "uf_sigla", "regiao", "subgrupo_codigo", "subgrupo_nome", "qtd_internacoes",
            "valor_total", "custo_por_internacao", "custo_esperado", "z_robusto", "direcao_atipicidade",
            "excesso_estimado"]
    return (scored.loc[scored["atipico"], cols]
            .sort_values("z_robusto", key=np.abs, ascending=False)
            .reset_index(drop=True))
