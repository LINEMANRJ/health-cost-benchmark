import numpy as np
import pandas as pd
import pytest

from hcb.analysis import outliers, statistics
from hcb.processing.cleaning import clean
from hcb.processing.transform import transform
from hcb.processing.validation import validate


def test_holm_adjust_known_values():
    p = pd.Series([0.01, 0.04, 0.03])
    adj = statistics.holm_adjust(p)
    assert list(adj.round(4)) == [0.03, 0.06, 0.06]


def test_trend_recovers_known_growth():
    months = pd.date_range("2020-01-01", periods=36, freq="MS")
    series = pd.Series(100 * (1.10 ** (np.arange(36) / 12)), index=months)
    res = statistics.trend(series)
    assert res["crescimento_anual"] == pytest.approx(0.10, abs=1e-6)
    assert res["p_valor"] < 0.001


def test_trend_requires_minimum_points():
    res = statistics.trend(pd.Series([1.0, 2.0, 3.0]))
    assert np.isnan(res["crescimento_anual"])


def test_trends_by_region(clean_fact):
    t = statistics.trends_by(clean_fact, "regiao")
    assert set(t["regiao"]) == set(clean_fact["regiao"].unique())
    assert (t["tendencia"] == "alta").all()  # reajuste nominal embutido na base sintética


def test_variation_between_ufs(clean_fact):
    v = statistics.variation_between_ufs(clean_fact)
    assert (v["cv_entre_ufs"] > 0).all()
    assert (v["maior_custo"] >= v["menor_custo"]).all()


def test_regional_differences_detects_built_in_gap(clean_fact):
    r = statistics.regional_differences(clean_fact)
    assert r["p_ajustado_holm"].between(0, 1).all()
    # A base sintética embute fatores regionais de custo — deve haver diferença em algum subgrupo.
    assert r["diferenca_significativa"].any()


def test_outlier_detection_recovers_injected_anomalies(synthetic_result, ufs, subgroups):
    df, _ = clean(synthetic_result.data.astype(str).replace({"nan": "", "None": ""}))
    approved, _, _ = validate(df, set(ufs["uf_sigla"]), set(subgroups["subgrupo_codigo"]))
    fact = transform(approved, ufs, subgroups)
    scored = outliers.detect_outliers(fact)
    keys = ["competencia", "uf_sigla", "subgrupo_codigo"]
    truth = synthetic_result.ground_truth.query("tipo == 'custo_inflado'")[keys]
    flagged = scored.loc[scored["atipico"], keys]
    hits = truth.merge(flagged, on=keys)
    recall = len(hits) / len(truth)
    precision = len(hits) / len(flagged)
    assert recall >= 0.9
    assert precision >= 0.5
    assert (scored.loc[scored["atipico"], "qtd_internacoes"] >= 5).all()


def test_no_outliers_flagged_in_small_cells():
    rng = np.random.default_rng(0)
    rows = []
    for m in range(1, 13):
        for uf in ["A", "B", "C"]:
            n = int(rng.integers(1, 4))  # abaixo do mínimo de 5
            rows.append({"competencia": f"2023-{m:02d}", "uf_sigla": uf, "regiao": "Sul",
                         "subgrupo_codigo": "X", "subgrupo_nome": "X", "qtd_internacoes": n,
                         "valor_total": 1000.0 * n * (10 if m == 6 else 1)})
    df = pd.DataFrame(rows)
    df["custo_por_internacao"] = df["valor_total"] / df["qtd_internacoes"]
    assert not outliers.detect_outliers(df)["atipico"].any()
