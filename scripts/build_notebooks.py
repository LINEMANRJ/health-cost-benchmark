"""Gera e executa os notebooks de análise (notebooks/*.ipynb) a partir de células versionadas aqui.

Manter a fonte em um script facilita revisão de código (diffs legíveis) e garante que os
notebooks publicados foram executados de ponta a ponta. Uso: python scripts/build_notebooks.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbconvert.preprocessors import ExecutePreprocessor

ROOT = Path(__file__).resolve().parents[1]
NB_DIR = ROOT / "notebooks"

SETUP = """\
import sys
from pathlib import Path
ROOT = Path.cwd().resolve()
while not (ROOT / "pyproject.toml").exists() and ROOT != ROOT.parent:
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from hcb.config import load_settings
from hcb.analysis import indicators, statistics, outliers
from hcb.pipeline import FACT_FILE, run
from hcb.schema import REGION_ORDER

pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
pd.set_option("display.width", 140)
plt.rcParams.update({"figure.figsize": (10, 4), "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e1e0d9", "axes.titlelocation": "left"})
REGION_COLORS = {"Norte": "#2a78d6", "Nordeste": "#eb6834", "Centro-Oeste": "#1baf7a",
                 "Sudeste": "#eda100", "Sul": "#e87ba4"}

settings = load_settings()
if not (settings.processed_dir / FACT_FILE).exists():
    run(settings)
fact = pd.read_csv(settings.processed_dir / FACT_FILE, dtype={"subgrupo_codigo": str, "grupo_codigo": str},
                   parse_dates=["data"])
fact["regiao"] = pd.Categorical(fact["regiao"], categories=REGION_ORDER, ordered=True)
print(f"{len(fact):,} linhas | {fact['competencia'].min()} a {fact['competencia'].max()}")
"""

EDA = [
    ("md", """# 01 — Análise exploratória

**Pergunta de negócio:** onde está o gasto hospitalar e como ele se comporta no tempo, entre regiões e entre
categorias de procedimento?

> ⚠️ Executado sobre a **base sintética** do projeto (ver `docs/data_sources.md`). Os números ilustram o
> método; não descrevem a realidade do SUS.

Unidade de análise: **competência × UF × subgrupo SIGTAP** (dados agregados, sem informação individual)."""),
    ("code", SETUP),
    ("md", "## 1. Estrutura e completude"),
    ("code", """\
display(fact.head())
print("Células por região:"); display(fact.groupby("regiao", observed=True).size().rename("celulas").to_frame())
print("Nulos por coluna:"); display(fact.isna().sum()[lambda s: s > 0].rename("nulos").to_frame())"""),
    ("md", """## 2. KPIs gerais
O custo médio é **ponderado** (Σ valor ÷ Σ internações). A média simples das células daria o mesmo peso a
uma UF pequena e a São Paulo — por isso não é usada."""),
    ("code", """\
k = indicators.kpis(fact)
pd.Series(k).to_frame("valor")"""),
    ("md", "## 3. Como os custos evoluem ao longo do tempo?"),
    ("code", """\
m = indicators.monthly(fact, "regiao")
fig, ax = plt.subplots()
for r in REGION_ORDER:
    p = m[m["regiao"] == r]
    ax.plot(p["data"], p["custo_medio_por_internacao"], color=REGION_COLORS[r], lw=2, label=r)
ax.set_title("Custo médio por internação por região (R$ nominais)")
ax.legend(ncol=5, loc="upper left", frameon=False)
plt.show()

total = indicators.monthly(fact)
total[["data", "custo_medio_por_internacao", "media_movel_3m", "variacao_12m"]].tail(12)"""),
    ("md", """**Leitura:** tendência de alta em todas as regiões (a base sintética embute ~6% a.a. de reajuste
nominal). Os picos isolados em algumas regiões coincidem com as células atípicas analisadas no notebook 03 —
uma única célula de grande volume pode deslocar a média mensal de uma região inteira."""),
    ("md", "## 4. Distribuição dos custos"),
    ("code", """\
order = fact.groupby("subgrupo_nome")["custo_por_internacao"].median().sort_values().index
fig, ax = plt.subplots(figsize=(10, 7))
ax.boxplot([np.log10(fact.loc[fact["subgrupo_nome"] == n, "custo_por_internacao"]) for n in order],
           orientation="horizontal", tick_labels=[n[:40] for n in order], flierprops={"markersize": 3})
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R$ {10**v:,.0f}".replace(",", ".")))
ax.set_title("Custo por internação por subgrupo (escala log; cada ponto = UF × mês)")
plt.show()"""),
    ("md", """A distribuição é **assimétrica à direita** e varia em ordens de grandeza entre subgrupos (parto
≈ R$ 800 vs. transplante ≈ R$ 35 mil). Por isso: (i) comparações são feitas *dentro* do subgrupo, (ii) usa-se
escala log e (iii) estatísticas robustas (mediana, IQR, MAD)."""),
    ("md", "## 5. Quais grupos concentram maior volume financeiro?"),
    ("code", """\
table, summary = indicators.concentration(fact, "subgrupo_nome", 0.8)
print(summary)
table.head(10)"""),
    ("md", "## 6. Comparação entre regiões — bruta vs. ajustada ao mix"),
    ("code", """\
reg = indicators.summarize(fact, "regiao").merge(indicators.mix_adjusted_index(fact, "regiao"), on="regiao")
reg = reg.merge(indicators.utilization_rate(fact, "regiao"), on="regiao")
reg[["regiao", "custo_medio_por_internacao", "indice_custo_ajustado", "internacoes_por_10mil_hab_mes",
     "participacao_valor"]]"""),
    ("md", """O **índice ajustado ao mix** compara cada região com o que ela custaria se cada internação tivesse
o custo nacional do seu subgrupo no mesmo mês. Ele separa "faz procedimentos mais caros" de "paga mais pelo
mesmo tipo de procedimento". Ainda assim, **não controla gravidade dentro do subgrupo**, portanto diferenças
não devem ser lidas como ineficiência sem investigação adicional."""),
]

STATS = [
    ("md", """# 02 — Análise estatística

Testes para responder, com incerteza explícita:
1. A tendência de custo é consistente? (Theil–Sen + Mann–Kendall)
2. Quais categorias variam mais entre UFs? (CV, P90/P10)
3. Há diferença entre regiões dentro do mesmo subgrupo? (Kruskal–Wallis, ε², Holm)
4. Volume e custo estão associados? (Spearman) — **associação, não causalidade**

> ⚠️ Base sintética — resultados ilustrativos."""),
    ("code", SETUP),
    ("md", """## 1. Tendência
Theil–Sen estima a inclinação mediana entre todos os pares de pontos — robusta a meses atípicos. Aplicada ao
log do custo médio mensal, a inclinação vira taxa de crescimento composta anual."""),
    ("code", """\
statistics.trends_by(fact, "subgrupo_nome")[["subgrupo_nome", "crescimento_anual", "ic95_inf", "ic95_sup",
                                             "p_ajustado_holm", "tendencia"]]"""),
    ("md", "## 2. Variação entre UFs por subgrupo"),
    ("code", "statistics.variation_between_ufs(fact)"),
    ("md", """## 3. Diferenças regionais
Unidade = UF no período inteiro (n ≤ 27 por subgrupo). Usar UF × mês inflaria artificialmente o n com meses
correlacionados (pseudo-replicação). ε² ≥ 0,26 é considerado efeito grande."""),
    ("code", """\
statistics.regional_differences(fact)[["subgrupo_nome", "ufs", "h", "p_ajustado_holm", "epsilon2",
                                       "magnitude_efeito", "regiao_maior_mediana", "regiao_menor_mediana"]]"""),
    ("md", "## 4. Volume × custo (Spearman)"),
    ("code", "statistics.spearman_volume_cost(fact).sort_values('rho_spearman')"),
    ("md", """**Cuidados de interpretação.** Uma correlação entre volume e custo pode refletir perfil de casos
(centros de referência recebem casos mais graves), estrutura de rede, tabelas complementares estaduais ou
diferenças de registro. Nenhuma das análises acima permite afirmar que *aumentar* ou *reduzir* volume
alteraria o custo."""),
]

OUTLIERS = [
    ("md", """# 03 — Detecção de valores atípicos

Método: resíduo em log do custo por internação vs. esperado (mesmo subgrupo e UF, ajustado ao nível nacional do
mês), padronizado por um modelo de variância `a/n + b` (ruído amostral + sobredispersão, como em funnel plots).
Detalhes em `docs/methodology.md`.

A base sintética tem **anomalias injetadas com gabarito** (`data/raw/*_gabarito.csv`), o que permite medir
precisão e recall do método — algo raramente possível com dados reais.

> ⚠️ Base sintética — resultados ilustrativos."""),
    ("code", SETUP),
    ("code", """\
o = settings.outliers
scored = outliers.detect_outliers(fact, o["z_threshold"], o["min_admissions"])
flagged = outliers.outlier_table(scored)
print(f"Células atípicas: {len(flagged)} de {scored['z_robusto'].notna().sum():,} avaliadas")
flagged.head(10)"""),
    ("code", """\
ratio = scored["custo_por_internacao"] / scored["custo_esperado"]
flag = scored["atipico"]
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.scatter(scored.loc[~flag, "qtd_internacoes"], ratio[~flag], s=5, color="#b8b6ae", alpha=0.5, label="Esperado")
ax.scatter(scored.loc[flag, "qtd_internacoes"], ratio[flag], s=25, color="#d03b3b", label="Atípico")
ax.axhline(1, color="black", lw=1); ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("Internações na célula"); ax.set_ylabel("Observado ÷ esperado"); ax.legend(frameon=False)
ax.set_title("Funnel plot: a dispersão aceitável diminui com o volume da célula")
plt.show()"""),
    ("md", "## Validação contra o gabarito"),
    ("code", """\
gab_path = settings.raw_file.with_name(settings.raw_file.stem + "_gabarito.csv")
if settings.source_type == "synthetic" and gab_path.exists():
    keys = ["competencia", "uf_sigla", "subgrupo_codigo"]
    truth = pd.read_csv(gab_path, dtype=str).query("tipo == 'custo_inflado'")[keys]
    hits = truth.merge(flagged[keys], on=keys)
    precision, recall = len(hits) / len(flagged), len(hits) / len(truth)
    print(f"Anomalias injetadas: {len(truth)} | sinalizadas: {len(flagged)} | acertos: {len(hits)}")
    print(f"Precisão: {precision:.1%} | Recall: {recall:.1%}")
    for thr in [3.0, 3.5, 4.0, 5.0]:
        f = scored[scored["z_robusto"].abs() > thr][keys]
        h = truth.merge(f, on=keys)
        prec, rec = len(h) / max(len(f), 1), len(h) / len(truth)
        print(f"  limiar {thr}: sinalizadas={len(f):>4}  precisão={prec:.1%}  recall={rec:.1%}")"""),
    ("md", """**Leitura:** o limiar controla o equilíbrio entre falsos positivos (custo de auditoria) e falsos
negativos (risco não detectado). Na prática, calibre o limiar com a capacidade da equipe de auditoria e
valide uma amostra de casos sinalizados. Atipicidade **não** comprova erro, fraude ou ineficiência."""),
]


def build(name: str, cells: list[tuple[str, str]]) -> Path:
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.cells = [nbformat.v4.new_markdown_cell(src) if kind == "md" else nbformat.v4.new_code_cell(src)
                for kind, src in cells]
    ExecutePreprocessor(timeout=600, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(NB_DIR)}})
    path = NB_DIR / name
    nbformat.write(nb, path)
    print("  ", path)
    return path


def main() -> int:
    NB_DIR.mkdir(exist_ok=True)
    build("01_analise_exploratoria.ipynb", EDA)
    build("02_analise_estatistica.ipynb", STATS)
    build("03_deteccao_atipicos.ipynb", OUTLIERS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
