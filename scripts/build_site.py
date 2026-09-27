"""Gera o site estático do projeto (GitHub Pages) em `site/`.

O dashboard Streamlit precisa de um servidor Python; o GitHub Pages só serve arquivos
estáticos. Este script reaproveita os mesmos cálculos (src/hcb) e os mesmos gráficos
(dashboard/charts.py) para publicar uma página com gráficos Plotly interativos.

Uso: python scripts/build_site.py [--output site]   (roda o pipeline se necessário)
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "dashboard"):
    sys.path.insert(0, str(p))

import charts  # noqa: E402
import pandas as pd  # noqa: E402
import plotly  # noqa: E402

from hcb.analysis import indicators, outliers, statistics  # noqa: E402
from hcb.config import load_settings  # noqa: E402
from hcb.formatting import brl, brl_compact, number, pct  # noqa: E402
from hcb.pipeline import FACT_FILE, run  # noqa: E402
from hcb.schema import REGION_ORDER  # noqa: E402

REPO_URL = "https://github.com/LINEMANRJ/health-cost-benchmark"
BLOB = f"{REPO_URL}/blob/main"

CSS = """
:root { color-scheme: light; --bg:#f9f9f7; --surface:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --line:rgba(11,11,11,.10); --accent:#2a78d6; --warn-bg:#fff4db; --warn-ink:#7a5200; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
a { color:var(--accent); }
.wrap { max-width:1120px; margin:0 auto; padding:0 16px; }
header.hero { background:var(--card); border-bottom:1px solid var(--line); padding:48px 0 32px; }
.eyebrow { font-size:.8rem; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:var(--ink2); }
h1 { font-size:clamp(2rem,5vw,2.8rem); line-height:1.1; margin:.3rem 0 .6rem; }
.lead { font-size:1.1rem; color:var(--ink2); max-width:760px; margin:0 0 1rem; }
.badge { display:inline-block; padding:4px 12px; border-radius:999px; font-size:.82rem; font-weight:600;
  background:var(--warn-bg); color:var(--warn-ink); border:1px solid #f3d38a; }
.actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:20px; }
.btn { display:inline-block; padding:9px 16px; border-radius:8px; font-weight:600; font-size:.92rem;
  text-decoration:none; border:1px solid var(--line); background:var(--card); color:var(--ink); }
.btn.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:28px 0 0; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.kpi .label { font-size:.8rem; color:var(--ink2); }
.kpi .value { font-size:1.45rem; font-weight:650; margin-top:2px; }
.kpi .note { font-size:.78rem; color:var(--muted); }
nav.toc { position:sticky; top:0; z-index:5; background:rgba(249,249,247,.95); backdrop-filter:blur(6px);
  border-bottom:1px solid var(--line); }
nav.toc .wrap { display:flex; gap:18px; overflow-x:auto; padding-top:10px; padding-bottom:10px; white-space:nowrap; }
nav.toc a { color:var(--ink2); text-decoration:none; font-size:.9rem; font-weight:500; }
nav.toc a:hover { color:var(--accent); }
section { padding:40px 0 8px; }
h2 { font-size:1.5rem; margin:0 0 .3rem; }
h3 { font-size:1.05rem; margin:1.6rem 0 .2rem; }
.answer { color:var(--ink2); max-width:860px; margin:.2rem 0 1rem; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px; margin:12px 0; }
.card { overflow:hidden; }
table { width:100%; border-collapse:collapse; font-size:.9rem; background:var(--card); }
th, td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
th { font-weight:600; color:var(--ink2); background:#f4f3ef; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; }
.flow { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:12px 0; }
.step { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px 12px; font-size:.88rem; }
.step b { display:block; font-size:.92rem; }
.arrow { color:var(--muted); }
pre { background:#0d0d0d; color:#f4f3ef; padding:14px 16px; border-radius:10px; overflow-x:auto; font-size:.85rem; }
.caveat { border-left:3px solid #eda100; background:var(--card); padding:10px 14px; border-radius:0 8px 8px 0;
  color:var(--ink2); font-size:.92rem; }
footer { margin-top:48px; padding:28px 0 40px; border-top:1px solid var(--line); color:var(--ink2); font-size:.88rem; }
@media (max-width:640px) { header.hero { padding-top:32px; } .kpi .value { font-size:1.2rem; } }
"""


def _fig(fig, first: bool = False) -> str:
    fig.update_layout(autosize=True)
    return fig.to_html(full_html=False, include_plotlyjs=False, default_width="100%",
                       config={"displaylogo": False, "responsive": True,
                               "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def _table(df: pd.DataFrame, columns: dict[str, tuple[str, callable | None]]) -> str:
    head = "".join(
        f'<th class="{"num" if fmt else ""}">{html.escape(label)}</th>' for label, fmt in columns.values())
    rows = []
    for _, r in df.iterrows():
        cells = []
        for col, (_, fmt) in columns.items():
            value = fmt(r[col]) if fmt else html.escape(str(r[col]))
            cells.append(f'<td class="{"num" if fmt else ""}">{value}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def load(settings):
    if not (settings.processed_dir / FACT_FILE).exists():
        run(settings)
    fact = pd.read_csv(settings.processed_dir / FACT_FILE, dtype={"subgrupo_codigo": str, "grupo_codigo": str},
                       parse_dates=["data"])
    fact["regiao"] = pd.Categorical(fact["regiao"], categories=REGION_ORDER, ordered=True)
    quality = json.loads((settings.reports_dir / "quality_report.json").read_text(encoding="utf-8"))
    return fact, quality


def build(output: Path) -> Path:
    settings = load_settings()
    fact, quality = load(settings)
    o = settings.outliers
    scored = outliers.detect_outliers(fact, float(o["z_threshold"]), int(o["min_admissions"]))
    flagged = outliers.outlier_table(scored)
    k = indicators.kpis(fact)
    synthetic = settings.source_type == "synthetic"

    monthly_region = indicators.monthly(fact, "regiao")
    monthly_total = indicators.monthly(fact)
    trends_rg = statistics.trends_by(fact, "regiao")
    variation = statistics.variation_between_ufs(fact)
    regional = statistics.regional_differences(fact)
    mix_uf = indicators.mix_adjusted_index(fact, "uf_sigla").merge(
        fact[["uf_sigla", "regiao"]].drop_duplicates(), on="uf_sigla")
    by_region = (indicators.summarize(fact, "regiao")
                 .merge(indicators.utilization_rate(fact, "regiao"), on="regiao")
                 .merge(indicators.mix_adjusted_index(fact, "regiao")[["regiao", "indice_custo_ajustado"]],
                        on="regiao")
                 .sort_values("indice_custo_ajustado", ascending=False))
    conc_table, conc = indicators.concentration(fact, "subgrupo_nome", float(settings.analysis["pareto_share"]))
    above = flagged[flagged["z_robusto"] > 0]
    n_sig = int(regional["diferenca_significativa"].sum())
    total_tr = statistics.trend(monthly_total.set_index("data")["custo_medio_por_internacao"])

    f_time = _fig(charts.time_series(monthly_region, "custo_medio_por_internacao", "Custo médio", "regiao", True),
                  first=True)
    f_yoy = _fig(charts.yoy_bars(monthly_total))
    f_box = _fig(charts.box_by_subgroup(fact))
    f_mix = _fig(charts.mix_index_bars(mix_uf))
    f_pareto = _fig(charts.pareto_bars(conc_table))
    f_out = _fig(charts.outlier_scatter(scored, float(o["z_threshold"])))

    kpi_tiles = [
        ("Valor aprovado", brl_compact(k["valor_total"]), f"{k['periodo_inicio']} a {k['periodo_fim']}"),
        ("Internações", number(k["internacoes"]), f"{k['meses']} meses"),
        ("Custo médio / internação", brl(k["custo_medio_por_internacao"], 0), "Σ valor ÷ Σ internações"),
        ("Mediana ponderada", brl(k["custo_mediano_ponderado"], 0), "menos sensível a extremos"),
        ("Variação 12 meses", pct(k["variacao_12m_custo_medio"], signed=True), "custo médio"),
        ("Células atípicas", number(len(flagged)), f"abs(z) > {number(float(o['z_threshold']), 1)}"),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="label">{a}</div><div class="value">{b}</div>'
                       f'<div class="note">{c}</div></div>' for a, b, c in kpi_tiles)

    trend_table = _table(trends_rg, {
        "regiao": ("Região", None),
        "crescimento_anual": ("Crescimento anual", lambda v: pct(v, signed=True)),
        "ic95_inf": ("IC95% inf.", pct), "ic95_sup": ("IC95% sup.", pct),
        "p_ajustado_holm": ("p (Holm)", lambda v: f"{v:.1e}".replace(".", ",")),
    })
    region_table = _table(by_region, {
        "regiao": ("Região", None),
        "custo_medio_por_internacao": ("Custo médio", lambda v: brl(v, 0)),
        "indice_custo_ajustado": ("Índice ajustado ao mix", lambda v: number(v, 3)),
        "internacoes_por_10mil_hab_mes": ("Intern./10 mil hab./mês", lambda v: number(v, 1)),
        "participacao_valor": ("Part. no valor", pct),
    })
    var_table = _table(variation.head(6), {
        "subgrupo_nome": ("Subgrupo", None),
        "cv_entre_ufs": ("CV entre UFs", pct),
        "razao_p90_p10": ("P90/P10", lambda v: number(v, 2)),
        "uf_menor_custo": ("UF menor custo", None),
        "uf_maior_custo": ("UF maior custo", None),
    })
    out_table = _table(flagged.head(10), {
        "competencia": ("Competência", None), "uf_sigla": ("UF", None), "subgrupo_nome": ("Subgrupo", None),
        "qtd_internacoes": ("Internações", number),
        "custo_por_internacao": ("Custo/intern.", lambda v: brl(v, 0)),
        "custo_esperado": ("Esperado", lambda v: brl(v, 0)),
        "z_robusto": ("z", lambda v: number(v, 1)),
    })
    rules_ok = sum(1 for r in quality["rules"] if r["failed_rows"] == 0)

    banner = ('<p><span class="badge">⚠️ BASE SINTÉTICA — números ilustrativos, não descrevem o SUS</span></p>'
              if synthetic else "")
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Health Cost Benchmark</title>
<meta name="description" content="Benchmark analítico de custos e economicidade de internações hospitalares com dados abertos do SUS: pipeline validado, indicadores, estatística e detecção de atípicos.">
<meta property="og:title" content="Health Cost Benchmark">
<meta property="og:description" content="Custos e economicidade em saúde com dados abertos (SIH/SUS).">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📊</text></svg>">
<style>{CSS}</style>
<script src="plotly.min.js"></script>
</head>
<body>
<header class="hero"><div class="wrap">
  <div class="eyebrow">Data &amp; AI aplicado à saúde</div>
  <h1>Health Cost Benchmark</h1>
  <p class="lead">Onde o gasto hospitalar cresce, quem paga mais pelo mesmo tipo de procedimento e quais
  registros merecem auditoria. Pipeline com validação de qualidade, indicadores com metodologia explícita,
  estatística robusta e detecção de atípicos, no modelo do SIH/SUS (AIH aprovadas por mês × UF × subgrupo SIGTAP).</p>
  {banner}
  <div class="actions">
    <a class="btn primary" href="{REPO_URL}">Ver código no GitHub</a>
    <a class="btn" href="{BLOB}/docs/methodology.md">Metodologia</a>
    <a class="btn" href="{BLOB}/docs/data_sources.md">Fonte dos dados</a>
    <a class="btn" href="#executar">Executar o dashboard</a>
  </div>
  <div class="kpis">{kpi_html}</div>
</div></header>

<nav class="toc"><div class="wrap">
  <a href="#tempo">1. Evolução</a><a href="#variacao">2. Variação</a><a href="#atipicos">3. Atípicos</a>
  <a href="#regioes">4. Regiões</a><a href="#concentracao">5. Concentração</a><a href="#qualidade">Qualidade</a>
  <a href="#como-funciona">Como funciona</a><a href="#executar">Executar</a>
</div></nav>

<main class="wrap">
<section id="tempo">
  <h2>1. Como os custos evoluem ao longo do tempo?</h2>
  <p class="answer">O custo médio por internação cresce <b>{pct(total_tr['crescimento_anual'], signed=True)} ao ano</b>
  (Theil–Sen; IC95% {pct(total_tr['ic95_inf'])} a {pct(total_tr['ic95_sup'])}). A alta aparece em todas as regiões.
  Os picos isolados não são tendência: são células atípicas de alto volume (seção 3). Os valores são nominais.</p>
  <div class="card">{f_time}</div>
  <h3>O custo está acelerando?</h3><p class="answer">Variação de cada mês contra o mesmo mês do ano anterior.</p>
  <div class="card">{f_yoy}</div>
  <h3>A tendência é consistente por região?</h3><p class="answer">Mann–Kendall com correção de Holm.</p>
  {trend_table}
</section>

<section id="variacao">
  <h2>2. Quais categorias apresentam maior variação?</h2>
  <p class="answer">Os custos variam em ordens de grandeza entre subgrupos, por isso a comparação é sempre
  <b>dentro do subgrupo</b>. Cada ponto é uma célula UF × mês (escala log). A tabela mostra a dispersão do custo
  médio entre UFs.</p>
  <div class="card">{f_box}</div>
  {var_table}
</section>

<section id="atipicos">
  <h2>3. Existem valores atípicos?</h2>
  <p class="answer"><b>{len(flagged)} células</b> fogem do esperado para o mesmo subgrupo e UF, já ajustado ao nível
  nacional do mês. {len(above)} estão acima do esperado, com excesso estimado de <b>{brl_compact(above['excesso_estimado'].sum())}</b>.
  O limiar considera o tamanho da célula (funnel plot com sobredispersão). Na base sintética, que traz gabarito,
  o método encontrou 100% das anomalias injetadas.</p>
  <div class="card">{f_out}</div>
  {out_table}
  <p class="caveat">Atipicidade é um sinal para priorizar a auditoria. Não comprova erro, fraude ou ineficiência.</p>
</section>

<section id="regioes">
  <h2>4. Existem diferenças relevantes entre regiões?</h2>
  <p class="answer">O <b>índice ajustado ao mix</b> compara o gasto observado com o que a UF gastaria pagando o custo
  médio nacional de cada subgrupo no mesmo mês (padronização indireta); 1 é o esperado. O Kruskal–Wallis por
  subgrupo, com a UF como unidade, encontrou diferença significativa em <b>{n_sig} de {len(regional)}</b> subgrupos.</p>
  <div class="card">{f_mix}</div>
  {region_table}
  <p class="caveat">São associações, não causas. O ajuste controla o subgrupo de procedimento, mas não a gravidade,
  a idade nem o fluxo de pacientes entre UFs.</p>
</section>

<section id="concentracao">
  <h2>5. Quais grupos concentram maior volume financeiro?</h2>
  <p class="answer"><b>{conc['itens_para_participacao_alvo']} de {conc['itens']}</b> subgrupos (em azul) respondem por
  {pct(conc['participacao_alvo'], 0)} do valor total (HHI = {number(conc['hhi'])}).</p>
  <div class="card">{f_pareto}</div>
</section>

<section id="qualidade">
  <h2>Qualidade dos dados</h2>
  <p class="answer">Status <b>{html.escape(quality['status'])}</b>: {number(quality['rows_received'])} linhas recebidas,
  {number(quality['rows_approved'])} aprovadas e <b>{number(quality['rows_quarantined'])} em quarentena</b>
  ({pct(quality['rejected_ratio'], 2)}), com o motivo registrado. {rules_ok} de {len(quality['rules'])} regras
  passaram sem falhas. Linhas com erro não entram em nenhum indicador.
  <a href="{BLOB}/reports/quality_report.md">Relatório completo</a>.</p>
</section>

<section id="como-funciona">
  <h2>Como funciona</h2>
  <div class="flow">
    <div class="step"><b>Dados brutos</b>sintético · TabNet</div><span class="arrow">→</span>
    <div class="step"><b>Tratamento</b>formatos, duplicatas</div><span class="arrow">→</span>
    <div class="step"><b>Validação</b>13 regras + quarentena</div><span class="arrow">→</span>
    <div class="step"><b>Transformação</b>IBGE · SIGTAP</div><span class="arrow">→</span>
    <div class="step"><b>Indicadores</b>ponderados, mix, Pareto</div><span class="arrow">→</span>
    <div class="step"><b>Análise</b>tendência, testes, atípicos</div><span class="arrow">→</span>
    <div class="step"><b>Visualização</b>Streamlit · esta página</div>
  </div>
  <p class="answer">Stack: Python, pandas, SciPy, Plotly, Streamlit e pytest (52 testes), com CI no GitHub Actions.
  Esta página é gerada pelos mesmos módulos testados do pipeline.
  Veja a <a href="{BLOB}/docs/architecture.md">arquitetura</a>, o <a href="{BLOB}/docs/data_dictionary.md">dicionário de dados</a>
  e os <a href="{BLOB}/docs/future_improvements.md">próximos passos</a>: previsão, ML para anomalias e agente de IA.</p>
</section>

<section id="executar">
  <h2>Executar o dashboard interativo</h2>
  <p class="answer">O dashboard completo (filtros por período, região, UF e subgrupo, com limiar ajustável de
  atipicidade) roda localmente com Streamlit:</p>
<pre>git clone {REPO_URL}.git
cd health-cost-benchmark
pip install -r requirements.txt &amp;&amp; pip install -e . --no-deps
python -m hcb.pipeline
streamlit run dashboard/app.py</pre>
</section>
</main>

<footer><div class="wrap">
  Health Cost Benchmark · código sob licença MIT · gerado em {built}.
  {"Os dados exibidos são sintéticos. " if synthetic else ""}Dados reais do SIH/SUS pertencem ao Ministério da Saúde/DATASUS
  e devem ser citados conforme <a href="{BLOB}/docs/data_sources.md">docs/data_sources.md</a>.
</div></footer>
</body>
</html>
"""
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copytree(ROOT / "docs" / "images", output / "images")
    # plotly.js servido junto do site (sem dependência de CDN), na mesma versão do pacote Python.
    shutil.copy(Path(plotly.__file__).parent / "package_data" / "plotly.min.js", output / "plotly.min.js")
    return output / "index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    path = build(args.output.resolve())
    print(f"Site gerado em {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
