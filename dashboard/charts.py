"""Construtores de gráficos Plotly do dashboard (sem dependência do Streamlit)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from hcb.schema import REGION_ORDER

# Paleta categórica validada (ordem fixa; cor segue a entidade, não o ranking).
REGION_COLORS = {
    "Norte": "#2a78d6",
    "Nordeste": "#eb6834",
    "Centro-Oeste": "#1baf7a",
    "Sudeste": "#eda100",
    "Sul": "#e87ba4",
}
PRIMARY = "#2a78d6"
MUTED = "#b8b6ae"
CRITICAL = "#d03b3b"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"

LOG_COST_TICKS = [300, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000]


def _layout(fig: go.Figure, height: int = 380, **kw) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13, color=INK_2),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=GRID),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
        separators=",.",
        **kw,
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, ticks="outside", tickcolor=AXIS)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=AXIS)
    return fig


def time_series(df: pd.DataFrame, value: str, label: str, by: str | None, money: bool) -> go.Figure:
    fig = go.Figure()
    hover = "%{x|%m/%Y}<br>" + (f"{label}: R$ %{{y:,.2f}}" if money else f"{label}: %{{y:,.0f}}")
    if by:
        for region in [r for r in REGION_ORDER if r in set(df[by].astype(str))]:
            part = df[df[by].astype(str) == region]
            fig.add_trace(go.Scatter(
                x=part["data"], y=part[value], name=region, mode="lines",
                line=dict(width=2, color=REGION_COLORS[region]),
                hovertemplate=f"<b>{region}</b><br>" + hover + "<extra></extra>",
            ))
    else:
        fig.add_trace(go.Scatter(x=df["data"], y=df[value], name=label, mode="lines",
                                 line=dict(width=2, color=PRIMARY), hovertemplate=hover + "<extra></extra>"))
        if "media_movel_3m" in df and value == "custo_medio_por_internacao":
            fig.add_trace(go.Scatter(x=df["data"], y=df["media_movel_3m"], name="Média móvel 3 meses",
                                     mode="lines", line=dict(width=2, color=INK_2, dash="dot"),
                                     hovertemplate="Média móvel 3m: R$ %{y:,.2f}<extra></extra>"))
    fig = _layout(fig, hovermode="x unified")
    fig.update_xaxes(tickformat="%m/%Y")
    fig.update_yaxes(tickprefix="R$ " if money else "", tickformat="~s" if metric_is_large(df, value) else ",.0f",
                     rangemode="tozero" if not money else "normal")
    return fig


def metric_is_large(df: pd.DataFrame, value: str) -> bool:
    return bool(df[value].abs().max() >= 1e6)


def yoy_bars(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["variacao_12m"])
    colors = [CRITICAL if v > 0 else PRIMARY for v in d["variacao_12m"]]
    fig = go.Figure(go.Bar(x=d["data"], y=d["variacao_12m"], marker_color=colors,
                           hovertemplate="%{x|%m/%Y}: %{y:+.1%}<extra></extra>"))
    fig = _layout(fig, height=240, bargap=0.25)
    fig.update_xaxes(tickformat="%m/%Y")
    fig.update_yaxes(tickformat="+.0%", zeroline=True, zerolinecolor=AXIS)
    return fig


def box_by_subgroup(df: pd.DataFrame) -> go.Figure:
    order = (df.groupby("subgrupo_nome")["custo_por_internacao"].median().sort_values().index.tolist())
    fig = go.Figure()
    for name in order:
        part = df[df["subgrupo_nome"] == name]
        fig.add_trace(go.Box(
            x=part["custo_por_internacao"], name=_short(name), orientation="h",
            marker=dict(color=PRIMARY, size=4, outliercolor=CRITICAL), line=dict(color=PRIMARY, width=1.5),
            fillcolor="rgba(42,120,214,0.12)", boxpoints="outliers", showlegend=False,
            hovertemplate=f"<b>{name}</b><br>Custo/internação: R$ %{{x:,.2f}}<extra></extra>",
        ))
    fig = _layout(fig, height=max(380, 30 * len(order) + 60))
    fig.update_xaxes(type="log", tickprefix="R$ ", tickformat=",.0f", tickvals=LOG_COST_TICKS,
                     title="Custo por internação (escala log)", showgrid=True, gridcolor=GRID)
    return fig


def histogram(df: pd.DataFrame, subgroup: str) -> go.Figure:
    part = df[df["subgrupo_nome"] == subgroup]
    fig = go.Figure(go.Histogram(
        x=part["custo_por_internacao"], nbinsx=40, marker=dict(color=PRIMARY, line=dict(color=SURFACE, width=1)),
        hovertemplate="R$ %{x}<br>%{y} células<extra></extra>",
    ))
    med = part["custo_por_internacao"].median()
    fig.add_vline(x=med, line=dict(color=INK, width=1.5, dash="dash"),
                  annotation_text=f"mediana R$ {med:,.0f}".replace(",", "."), annotation_position="top right")
    fig = _layout(fig, height=300)
    fig.update_xaxes(title="Custo por internação (R$) — cada observação = UF × mês")
    fig.update_yaxes(title="Nº de células")
    return fig


def mix_index_bars(df: pd.DataFrame, key: str = "uf_sigla") -> go.Figure:
    d = df.sort_values("indice_custo_ajustado")
    fig = go.Figure()
    for region in REGION_ORDER:
        part = d[d["regiao"].astype(str) == region]
        if part.empty:
            continue
        fig.add_trace(go.Bar(
            y=part[key], x=part["indice_custo_ajustado"] - 1, base=1, orientation="h", name=region,
            marker=dict(color=REGION_COLORS[region]),
            customdata=np.stack([part["observado"], part["esperado"], part["indice_custo_ajustado"]], axis=1),
            hovertemplate="<b>%{y}</b><br>Índice: %{customdata[2]:.3f}<br>Observado: R$ %{customdata[0]:,.0f}"
                          "<br>Esperado p/ o mix: R$ %{customdata[1]:,.0f}<extra></extra>",
        ))
    fig.add_vline(x=1, line=dict(color=INK, width=1))
    fig = _layout(fig, height=max(360, 22 * len(d) + 60), barmode="overlay", bargap=0.3)
    fig.update_yaxes(categoryorder="array", categoryarray=d[key].tolist(), showgrid=False)
    fig.update_xaxes(title="Índice de custo ajustado ao mix (1 = esperado)", showgrid=True, gridcolor=GRID)
    return fig


def volume_cost_scatter(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for region in REGION_ORDER:
        part = df[df["regiao"].astype(str) == region]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["internacoes"], y=part["custo_medio_por_internacao"], mode="markers+text", name=region,
            text=part["uf_sigla"], textposition="top center", textfont=dict(size=10, color=INK_2),
            marker=dict(size=10, color=REGION_COLORS[region], line=dict(color=SURFACE, width=2)),
            hovertemplate="<b>%{text}</b><br>Internações: %{x:,.0f}<br>Custo médio: R$ %{y:,.2f}<extra></extra>",
        ))
    fig = _layout(fig, height=420)
    fig.update_xaxes(type="log", tickformat=",.0f", dtick=1, title="Internações no período (escala log)",
                     showgrid=True, gridcolor=GRID)
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.0f", title="Custo médio por internação")
    return fig


def pareto_bars(table: pd.DataFrame, label: str = "subgrupo_nome") -> go.Figure:
    d = table.iloc[::-1]
    colors = [PRIMARY if core else MUTED for core in d["nucleo_pareto"]]
    text = [f"{p:.1%}".replace(".", ",") + f" · acum. {c:.0%}" for p, c in zip(d["participacao"],
                                                                        d["participacao_acumulada"], strict=True)]
    fig = go.Figure(go.Bar(
        y=[_short(n) for n in d[label]], x=d["participacao"], orientation="h", marker_color=colors,
        text=text, textposition="outside", cliponaxis=False, textfont=dict(color=INK_2, size=11),
        customdata=d["valor_total"], hovertemplate="<b>%{y}</b><br>Participação: %{x:.1%}"
                                                    "<br>Valor: R$ %{customdata:,.0f}<extra></extra>",
    ))
    fig = _layout(fig, height=max(380, 28 * len(d) + 60), bargap=0.3)
    fig.update_xaxes(tickformat=".0%", title="Participação no valor total", showgrid=True, gridcolor=GRID,
                     range=[0, d["participacao"].max() * 1.35])
    return fig


def outlier_scatter(scored: pd.DataFrame, threshold: float) -> go.Figure:
    d = scored.dropna(subset=["z_robusto"])
    ratio = d["custo_por_internacao"] / d["custo_esperado"]
    flagged = d["z_robusto"].abs() > threshold
    fig = go.Figure()
    for is_out, name, color, size in [(False, "Dentro do esperado", MUTED, 5), (True, "Atípico", CRITICAL, 9)]:
        m = flagged == is_out
        part = d[m]
        fig.add_trace(go.Scattergl(
            x=part["qtd_internacoes"], y=ratio[m], mode="markers", name=name,
            marker=dict(color=color, size=size, opacity=0.9 if is_out else 0.45,
                        line=dict(color=SURFACE, width=1 if is_out else 0)),
            customdata=np.stack([part["competencia"], part["uf_sigla"], part["subgrupo_nome"],
                                 part["z_robusto"]], axis=1),
            hovertemplate="<b>%{customdata[1]} · %{customdata[0]}</b><br>%{customdata[2]}"
                          "<br>Internações: %{x:,.0f}<br>Observado/esperado: %{y:.2f}×"
                          "<br>z robusto: %{customdata[3]:.1f}<extra></extra>",
        ))
    fig.add_hline(y=1, line=dict(color=INK, width=1))
    fig = _layout(fig, height=420)
    fig.update_xaxes(type="log", tickformat=",.0f", dtick=1, title="Internações na célula (escala log)",
                     showgrid=True, gridcolor=GRID)
    fig.update_yaxes(type="log", tickvals=[0.5, 0.75, 1, 1.5, 2, 3, 5], ticksuffix="×",
                     title="Custo observado ÷ esperado (escala log)")
    return fig


def _short(text: str, limit: int = 42) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
