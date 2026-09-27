"""Previsão de custos — linha de base (ponto de partida para modelos de ML).

Implementa um baseline sazonal com deriva: previsão(t+h) = valor(t+h−12) × (1 + crescimento anual).
Todo modelo futuro (ETS, SARIMA, Prophet, gradient boosting) deve superar este baseline no backtest
`backtest()` para ser adotado. Ver docs/future_improvements.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    horizon: int
    mape: float
    forecasts: pd.DataFrame


def seasonal_drift_forecast(series: pd.Series, horizon: int = 6) -> pd.Series:
    """Previsão sazonal ingênua com deriva anual estimada nos últimos 12 meses.

    `series` deve ter índice mensal (DatetimeIndex, início do mês) e ≥ 24 observações.
    """
    y = series.dropna().sort_index()
    if len(y) < 24:
        raise ValueError("São necessários pelo menos 24 meses para o baseline sazonal com deriva.")
    growth = y.iloc[-12:].sum() / y.iloc[-24:-12].sum()
    index = pd.date_range(y.index[-1] + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    values = [y.iloc[len(y) - 12 + (h % 12)] * growth ** (1 + h // 12) for h in range(horizon)]
    return pd.Series(values, index=index, name="previsao")


def backtest(series: pd.Series, horizon: int = 6) -> BacktestResult:
    """Validação fora da amostra: treina até T−horizon e compara com os meses reservados."""
    y = series.dropna().sort_index()
    train, test = y.iloc[:-horizon], y.iloc[-horizon:]
    pred = seasonal_drift_forecast(train, horizon)
    frame = pd.DataFrame({"real": test.to_numpy(), "previsto": pred.to_numpy()}, index=test.index)
    mape = float(np.mean(np.abs(frame["previsto"] / frame["real"] - 1)))
    return BacktestResult(horizon=horizon, mape=mape, forecasts=frame)
