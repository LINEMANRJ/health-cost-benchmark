import pandas as pd
import pytest

from hcb import forecasting
from hcb.ai import tools


def test_seasonal_drift_forecast_on_pure_growth():
    idx = pd.date_range("2022-01-01", periods=36, freq="MS")
    s = pd.Series([100 * 1.05 ** (i // 12) for i in range(36)], index=idx)
    pred = forecasting.seasonal_drift_forecast(s, 3)
    assert list(pred.index.strftime("%Y-%m")) == ["2025-01", "2025-02", "2025-03"]
    assert pred.iloc[0] == pytest.approx(100 * 1.05**3)


def test_forecast_requires_history():
    with pytest.raises(ValueError):
        forecasting.seasonal_drift_forecast(pd.Series([1.0] * 10), 3)


def test_backtest_on_synthetic_series(clean_fact):
    m = clean_fact.groupby("data")["valor_total"].sum()
    res = forecasting.backtest(pd.concat([m, m.iloc[-12:].set_axis(
        pd.date_range(m.index[-1] + pd.offsets.MonthBegin(1), periods=12, freq="MS")) * 1.06]), 6)
    assert res.mape < 0.10
    assert len(res.forecasts) == 6


def test_agent_tools_dispatch(clean_fact):
    k = tools.call_tool(clean_fact, "get_kpis", {"filters": {"regiao": "Sul"}})
    assert k["internacoes"] > 0
    rows = tools.call_tool(clean_fact, "compare_by", {"dimension": "regiao"})
    assert {"regiao", "indice_custo_ajustado"} <= set(rows[0])
    assert "crescimento_anual" in tools.call_tool(clean_fact, "cost_trend")
    assert {s["name"] for s in tools.TOOL_SPECS} == set(tools.TOOLS)


def test_agent_tools_reject_invalid_input(clean_fact):
    with pytest.raises(KeyError):
        tools.call_tool(clean_fact, "drop_table")
    with pytest.raises(ValueError):
        tools.call_tool(clean_fact, "get_kpis", {"filters": {"senha": "x"}})
    with pytest.raises(ValueError):
        tools.call_tool(clean_fact, "get_kpis", {"filters": {"regiao": "Atlântida"}})
