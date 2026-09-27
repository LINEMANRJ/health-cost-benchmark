"""Gerador de base SINTÉTICA no formato-contrato do SIH/SUS agregado.

Os valores NÃO são dados reais. A base imita a estrutura e as ordens de grandeza
típicas da produção hospitalar do SUS (AIH aprovadas por UF × mês × subgrupo SIGTAP)
para que o projeto rode de ponta a ponta sem dependência de rede.

Mecanismos simulados (documentados em docs/data_sources.md):
- volume proporcional à população da UF, com fator regional de utilização;
- custo-base por subgrupo, fator regional/UF de custo e reajuste nominal ao longo do tempo;
- sazonalidade de volume (queda em dez/jan, pico respiratório em mai–jul nos clínicos);
- ruído amostral no custo médio proporcional a 1/sqrt(n) (média de n internações);
- anomalias injetadas (registradas em arquivo de gabarito) e problemas de qualidade
  (duplicatas, nulos, negativos, UF inválida, quantidade zero com valor positivo).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Parâmetros por subgrupo: custo médio de referência (R$), participação no volume,
# permanência média (dias). Ordens de grandeza plausíveis, não oficiais.
SUBGROUP_PARAMS: dict[str, tuple[float, float, float]] = {
    "0303": (1_100.0, 0.300, 5.5),
    "0304": (2_300.0, 0.040, 5.0),
    "0305": (1_500.0, 0.010, 6.0),
    "0308": (900.0, 0.030, 3.0),
    "0310": (700.0, 0.130, 2.2),
    "0403": (5_200.0, 0.015, 8.0),
    "0404": (900.0, 0.010, 2.0),
    "0405": (700.0, 0.010, 1.0),
    "0406": (7_800.0, 0.030, 7.0),
    "0407": (1_300.0, 0.110, 3.0),
    "0408": (2_100.0, 0.090, 4.0),
    "0409": (1_000.0, 0.050, 2.5),
    "0411": (850.0, 0.090, 2.3),
    "0415": (3_500.0, 0.020, 6.0),
    "0416": (3_800.0, 0.020, 5.0),
    "0505": (32_000.0, 0.001, 15.0),
}

# Subgrupos de alta complexidade concentrados em UFs com centros de referência.
HIGH_COMPLEXITY_UFS = {"SP", "MG", "RJ", "PR", "RS", "SC", "PE", "CE", "BA", "GO", "DF", "ES"}
CONCENTRATED_SUBGROUPS = {"0505"}

REGION_COST_FACTOR = {"Norte": 0.95, "Nordeste": 0.92, "Centro-Oeste": 1.02, "Sudeste": 1.08, "Sul": 1.10}
REGION_USE_FACTOR = {"Norte": 0.85, "Nordeste": 0.95, "Centro-Oeste": 1.00, "Sudeste": 1.00, "Sul": 1.15}

ADMISSIONS_PER_CAPITA_MONTH = 0.0049  # ~1 milhão de internações/mês no país
NOMINAL_GROWTH_MONTHLY = 0.005  # ~6% a.a. de reajuste nominal
UNIT_COST_CV = 0.60  # dispersão do custo entre internações individuais


@dataclass
class SyntheticResult:
    data: pd.DataFrame
    ground_truth: pd.DataFrame


def _seasonality(month: int, subgroup: str) -> float:
    factor = 1.0
    if month in (12, 1):
        factor *= 0.93
    if subgroup == "0303" and month in (5, 6, 7):
        factor *= 1.10
    return factor


def generate(
    ufs: pd.DataFrame,
    start: str = "2022-01",
    end: str = "2024-12",
    seed: int = 42,
    inject_quality_issues: bool = True,
    inject_anomalies: bool = True,
) -> SyntheticResult:
    """Gera a base sintética. `ufs` deve conter uf_sigla, regiao e populacao_censo_2022."""
    rng = np.random.default_rng(seed)
    months = pd.period_range(start=start, end=end, freq="M")
    if len(months) == 0:
        raise ValueError("Período sintético vazio: verifique start/end.")

    share_total = sum(p[1] for p in SUBGROUP_PARAMS.values())
    # Heterogeneidade estável por UF × subgrupo (perfil de casos, rede, tabela complementar).
    uf_sub_factor = {
        (uf, sg): float(np.exp(rng.normal(0, 0.07)))
        for uf in ufs["uf_sigla"]
        for sg in SUBGROUP_PARAMS
    }

    rows = []
    for t, period in enumerate(months):
        growth = (1 + NOMINAL_GROWTH_MONTHLY) ** t
        for uf in ufs.itertuples(index=False):
            base_volume = uf.populacao_censo_2022 * ADMISSIONS_PER_CAPITA_MONTH * REGION_USE_FACTOR[uf.regiao]
            for sg, (cost, share, los) in SUBGROUP_PARAMS.items():
                if sg in CONCENTRATED_SUBGROUPS and uf.uf_sigla not in HIGH_COMPLEXITY_UFS:
                    continue
                share_uf = share / share_total
                if sg in CONCENTRATED_SUBGROUPS:
                    share_uf *= 2.5  # concentra a produção nos centros de referência
                lam = base_volume * share_uf * _seasonality(period.month, sg)
                qtd = int(rng.poisson(lam))
                if qtd == 0:
                    continue
                mean_cost = (
                    cost
                    * growth
                    * REGION_COST_FACTOR[uf.regiao]
                    * uf_sub_factor[(uf.uf_sigla, sg)]
                )
                sigma = np.sqrt(UNIT_COST_CV**2 / qtd + 0.01**2)
                unit_cost = mean_cost * np.exp(rng.normal(-0.5 * sigma**2, sigma))
                los_cell = los * np.exp(rng.normal(0, 0.25 / np.sqrt(qtd) + 0.02))
                rows.append(
                    {
                        "competencia": str(period),
                        "uf_sigla": uf.uf_sigla,
                        "subgrupo_codigo": sg,
                        "qtd_internacoes": qtd,
                        "valor_total": round(unit_cost * qtd, 2),
                        "dias_permanencia": int(round(los_cell * qtd)),
                    }
                )

    df = pd.DataFrame(rows)
    truth = []

    anomaly_idx: np.ndarray = np.array([], dtype=int)
    if inject_anomalies:
        eligible = df.index[df["qtd_internacoes"] >= 20]
        anomaly_idx = rng.choice(eligible, size=min(40, len(eligible)), replace=False)
        multipliers = rng.uniform(2.5, 5.0, size=len(anomaly_idx))
        for i, m in zip(anomaly_idx, multipliers, strict=True):
            df.loc[i, "valor_total"] = round(df.loc[i, "valor_total"] * m, 2)
            truth.append({**df.loc[i, ["competencia", "uf_sigla", "subgrupo_codigo"]].to_dict(),
                          "tipo": "custo_inflado", "multiplicador": round(float(m), 2)})

    if inject_quality_issues:
        df = _inject_quality_issues(df, rng, truth, exclude=set(anomaly_idx.tolist()))

    ground_truth = pd.DataFrame(truth, columns=["competencia", "uf_sigla", "subgrupo_codigo", "tipo", "multiplicador"])
    return SyntheticResult(data=df.reset_index(drop=True), ground_truth=ground_truth)


def _inject_quality_issues(
    df: pd.DataFrame, rng: np.random.Generator, truth: list[dict], exclude: set[int]
) -> pd.DataFrame:
    df = df.copy()
    df["valor_total"] = df["valor_total"].astype(object)
    # Linhas disjuntas para cada tipo de problema (e distintas das anomalias injetadas).
    pool = list(rng.permutation([i for i in df.index if i not in exclude]))

    def pick(n: int) -> list[int]:
        return [pool.pop() for _ in range(n)]

    for i in pick(8):
        df.loc[i, "valor_total"] = None
        truth.append({**_key(df, i), "tipo": "valor_nulo", "multiplicador": np.nan})
    for i in pick(5):
        df.loc[i, "valor_total"] = -abs(float(df.loc[i, "valor_total"]))
        truth.append({**_key(df, i), "tipo": "valor_negativo", "multiplicador": np.nan})
    for i in pick(4):
        df.loc[i, "qtd_internacoes"] = 0
        truth.append({**_key(df, i), "tipo": "qtd_zero_com_valor", "multiplicador": np.nan})
    for i in pick(3):
        df.loc[i, "uf_sigla"] = "XX"
        truth.append({**_key(df, i), "tipo": "uf_invalida", "multiplicador": np.nan})
    # Formatação heterogênea (espaços/minúsculas) — deve ser corrigida na limpeza.
    for i in pick(30):
        df.loc[i, "uf_sigla"] = f" {str(df.loc[i, 'uf_sigla']).lower()} "

    dup_idx = pick(15)
    duplicates = df.loc[dup_idx].copy()
    for i in dup_idx:
        truth.append({**_key(df, i), "tipo": "duplicata", "multiplicador": np.nan})
    return pd.concat([df, duplicates], ignore_index=True)


def _key(df: pd.DataFrame, i: int) -> dict:
    return {
        "competencia": df.loc[i, "competencia"],
        "uf_sigla": str(df.loc[i, "uf_sigla"]).strip().upper(),
        "subgrupo_codigo": df.loc[i, "subgrupo_codigo"],
    }


def write(result: SyntheticResult, raw_file: Path) -> None:
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    result.data.to_csv(raw_file, index=False)
    result.ground_truth.to_csv(raw_file.with_name(raw_file.stem + "_gabarito.csv"), index=False)
