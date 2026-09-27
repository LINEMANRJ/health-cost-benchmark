"""Formatação numérica no padrão brasileiro (R$ 1.234,56)."""
from __future__ import annotations

import math


def _swap(text: str) -> str:
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def brl(value: float, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return "R$ " + _swap(f"{value:,.{decimals}f}")


def brl_compact(value: float) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    for size, suffix in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if abs(value) >= size:
            return "R$ " + _swap(f"{value / size:,.1f}") + suffix
    return brl(value)


def number(value: float, decimals: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return _swap(f"{value:,.{decimals}f}")


def pct(value: float, decimals: int = 1, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    fmt = f"{{:{'+' if signed else ''}.{decimals}f}}"
    return _swap(fmt.format(value * 100)) + "%"
