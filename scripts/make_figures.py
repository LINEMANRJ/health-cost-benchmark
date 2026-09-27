"""Gera as figuras estáticas usadas no README (docs/images/*.png).

Requer que o pipeline já tenha sido executado. Uso: python scripts/make_figures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from hcb.config import load_settings  # noqa: E402
from hcb.schema import REGION_ORDER  # noqa: E402

REGION_COLORS = {"Norte": "#2a78d6", "Nordeste": "#eb6834", "Centro-Oeste": "#1baf7a",
                 "Sudeste": "#eda100", "Sul": "#e87ba4"}
INK, INK2, GRID, SURFACE, MUTED, CRITICAL, PRIMARY = ("#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb",
                                                      "#b8b6ae", "#d03b3b", "#2a78d6")

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "axes.titlelocation": "left", "legend.frameon": False,
})
BRL = mticker.FuncFormatter(lambda v, _: "R$ " + f"{v:,.0f}".replace(",", "."))


def _save(fig, name: str, out: Path) -> None:
    fig.tight_layout()
    fig.savefig(out / name, dpi=150)
    plt.close(fig)
    print("  ", out / name)


def main() -> int:
    s = load_settings()
    ind = s.processed_dir / "indicadores"
    out = ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)

    m = pd.read_csv(ind / "serie_mensal_regiao.csv", parse_dates=["data"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for r in REGION_ORDER:
        part = m[m["regiao"] == r]
        ax.plot(part["data"], part["custo_medio_por_internacao"], color=REGION_COLORS[r], lw=2, label=r)
    ax.yaxis.set_major_formatter(BRL)
    ax.set_title("Como o custo médio por internação evolui? (por região, R$ nominais)")
    ax.legend(ncol=5, loc="upper left", bbox_to_anchor=(0, -0.08))
    ax.grid(axis="x", visible=False)
    _save(fig, "evolucao_custo_regiao.png", out)

    uf = pd.read_csv(ind / "por_uf.csv").sort_values("indice_custo_ajustado")
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.barh(uf["uf_sigla"], uf["indice_custo_ajustado"] - 1, left=1, height=0.65,
            color=[REGION_COLORS[r] for r in uf["regiao"]])
    ax.axvline(1, color=INK, lw=1)
    ax.set_title("Quais UFs custam mais do que o esperado para o seu mix? (índice ajustado ao mix)")
    ax.set_xlabel("Índice de custo ajustado ao mix (1 = esperado)")
    ax.grid(axis="y", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=REGION_COLORS[r]) for r in REGION_ORDER]
    ax.legend(handles, REGION_ORDER, ncol=5, loc="lower right")
    _save(fig, "indice_ajustado_uf.png", out)

    scored = pd.read_csv(s.processed_dir / "fato_internacoes_com_atipicidade.csv").dropna(subset=["z_robusto"])
    ratio = scored["custo_por_internacao"] / scored["custo_esperado"]
    flag = scored["atipico"].astype(bool)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.scatter(scored.loc[~flag, "qtd_internacoes"], ratio[~flag], s=6, color=MUTED, alpha=0.5,
               label="Dentro do esperado", lw=0)
    ax.scatter(scored.loc[flag, "qtd_internacoes"], ratio[flag], s=28, color=CRITICAL, label="Atípico",
               edgecolor=SURFACE, lw=1)
    ax.axhline(1, color=INK, lw=1)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(mticker.FixedLocator([0.75, 1, 1.5, 2, 3, 5]))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}×".replace(".", ",")))
    ax.yaxis.set_minor_locator(mticker.NullLocator())
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", ".")))
    ax.set_xlabel("Internações na célula (escala log)")
    ax.set_ylabel("Custo observado ÷ esperado")
    ax.set_title("Quais registros fogem do padrão esperado? (competência × UF × subgrupo)")
    ax.legend(loc="upper right")
    _save(fig, "atipicos_funnel.png", out)

    conc = pd.read_csv(ind / "concentracao_subgrupos.csv").iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = [n if len(n) <= 45 else n[:44] + "…" for n in conc["subgrupo_nome"]]
    ax.barh(labels, conc["participacao"], color=[PRIMARY if c else MUTED for c in conc["nucleo_pareto"]],
            height=0.65)
    for y, (p, c) in enumerate(zip(conc["participacao"], conc["participacao_acumulada"], strict=True)):
        ax.text(p + 0.003, y, f"{p:.1%}".replace(".", ",") + f" · acum. {c:.0%}", va="center", fontsize=8, color=INK2)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1, decimals=0))
    ax.set_xlim(0, conc["participacao"].max() * 1.3)
    ax.set_title("Quais subgrupos concentram o valor total?\n(azul = núcleo de Pareto que soma 80%)")
    ax.grid(axis="y", visible=False)
    _save(fig, "concentracao_pareto.png", out)
    return 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    sys.exit(main())
