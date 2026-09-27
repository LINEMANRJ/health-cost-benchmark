import math

import numpy as np
import pandas as pd
import pytest

from hcb.analysis import indicators


def _fact(rows):
    df = pd.DataFrame(rows)
    df["custo_por_internacao"] = df["valor_total"] / df["qtd_internacoes"]
    return df


@pytest.fixture
def tiny():
    return _fact([
        {"competencia": "2023-01", "data": pd.Timestamp("2023-01-01"), "uf_sigla": "SP", "regiao": "Sudeste",
         "populacao": 1000, "subgrupo_codigo": "A", "subgrupo_nome": "A", "qtd_internacoes": 10,
         "valor_total": 1000.0, "dias_permanencia": 20},
        {"competencia": "2023-01", "data": pd.Timestamp("2023-01-01"), "uf_sigla": "AC", "regiao": "Norte",
         "populacao": 500, "subgrupo_codigo": "A", "subgrupo_nome": "A", "qtd_internacoes": 30,
         "valor_total": 1500.0, "dias_permanencia": 60},
        {"competencia": "2023-01", "data": pd.Timestamp("2023-01-01"), "uf_sigla": "SP", "regiao": "Sudeste",
         "populacao": 1000, "subgrupo_codigo": "B", "subgrupo_nome": "B", "qtd_internacoes": 10,
         "valor_total": 5000.0, "dias_permanencia": 50},
    ])


def test_weighted_quantile_matches_unweighted_when_equal_weights():
    v = [1, 2, 3, 4, 5]
    assert indicators.weighted_quantile(v, [1] * 5, 0.5) == pytest.approx(3.0)


def test_weighted_quantile_respects_weights():
    # 99% do peso está em 10: a mediana ponderada fica próxima de 10 (interpolação entre pontos médios)
    assert 10.0 <= indicators.weighted_quantile([10, 100], [99, 1], 0.5) < 11.0
    assert math.isnan(indicators.weighted_quantile([], [], 0.5))


def test_kpis_weighted_average(tiny):
    k = indicators.kpis(tiny)
    assert k["valor_total"] == 7500
    assert k["internacoes"] == 50
    assert k["custo_medio_por_internacao"] == pytest.approx(150.0)  # 7500/50, não média das médias
    assert k["custo_mediano_celula"] == pytest.approx(100.0)  # mediana de [100, 50, 500]
    assert k["custo_por_dia"] == pytest.approx(7500 / 130)
    assert math.isnan(k["variacao_12m_custo_medio"])  # < 24 meses


def test_summarize_shares_sum_to_one(tiny):
    s = indicators.summarize(tiny, "regiao")
    assert s["participacao_valor"].sum() == pytest.approx(1.0)
    sp = s.set_index("regiao").loc["Sudeste"]
    assert sp["custo_medio_por_internacao"] == pytest.approx(6000 / 20)


def test_mix_adjusted_index(tiny):
    idx = indicators.mix_adjusted_index(tiny, "uf_sigla").set_index("uf_sigla")
    # Subgrupo A: custo nacional = 2500/40 = 62,5. SP esperado = 10*62,5 + 10*500 = 5625; observado 6000.
    assert idx.loc["SP", "indice_custo_ajustado"] == pytest.approx(6000 / 5625)
    assert idx.loc["AC", "indice_custo_ajustado"] == pytest.approx(1500 / (30 * 62.5))
    # O total observado e esperado coincidem nacionalmente (padronização indireta).
    assert idx["observado"].sum() == pytest.approx(idx["esperado"].sum())


def test_utilization_rate(tiny):
    r = indicators.utilization_rate(tiny, "uf_sigla").set_index("uf_sigla")
    assert r.loc["SP", "internacoes_por_10mil_hab_mes"] == pytest.approx(20 / 1000 * 10_000)


def test_concentration_pareto_and_hhi():
    df = pd.DataFrame({"cat": ["a", "b", "c", "d"], "valor_total": [70.0, 20.0, 5.0, 5.0]})
    table, summary = indicators.concentration(df, "cat", 0.8)
    assert summary["itens_para_participacao_alvo"] == 2
    assert summary["hhi"] == pytest.approx((0.49 + 0.04 + 0.0025 + 0.0025) * 10_000)
    assert table["participacao_acumulada"].iloc[-1] == pytest.approx(1.0)


def test_monthly_series_and_yoy(clean_fact):
    m = indicators.monthly(clean_fact)
    assert len(m) == 24
    assert m["variacao_12m"].iloc[:12].isna().all()
    assert m["variacao_12m"].iloc[12:].notna().all()
    # Base sintética tem reajuste nominal de ~6% a.a.
    assert 0.03 < m["variacao_12m"].iloc[12:].mean() < 0.09


def test_kpis_yoy_available_with_24_months(clean_fact):
    k = indicators.kpis(clean_fact)
    assert 0.03 < k["variacao_12m_custo_medio"] < 0.09
    assert np.isfinite(k["custo_mediano_ponderado"])
