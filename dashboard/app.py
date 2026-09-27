"""Health Cost Benchmark — dashboard analítico (Streamlit).

Execução:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "dashboard"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import charts  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from hcb.ai.agent import AgentError, Conversation, HealthCostAgent  # noqa: E402
from hcb.analysis import indicators, outliers, statistics  # noqa: E402
from hcb.config import load_settings  # noqa: E402
from hcb.formatting import brl, brl_compact, number, pct  # noqa: E402
from hcb.pipeline import FACT_FILE, run  # noqa: E402
from hcb.schema import REGION_ORDER  # noqa: E402

st.set_page_config(page_title="Health Cost Benchmark", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1400px;}
      [data-testid="stMetric"] {background: #ffffff; border: 1px solid rgba(11,11,11,0.10);
        border-radius: 10px; padding: 14px 16px;}
      [data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #52514e;}
      [data-testid="stMetricValue"] {font-size: 1.55rem;}
      .question {font-size: 1.02rem; font-weight: 600; color: #0b0b0b; margin: 0.4rem 0 0.1rem;}
      .answer {color: #52514e; font-size: 0.9rem; margin-bottom: 0.4rem;}
      .badge {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.78rem;
        font-weight: 600; background: #fff4db; color: #7a5200; border: 1px solid #f3d38a;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- dados
@st.cache_data(show_spinner="Carregando dados processados…")
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, dict, bool]:
    settings = load_settings()
    fact_path = settings.processed_dir / FACT_FILE
    quality_path = settings.reports_dir / "quality_report.json"
    if not fact_path.exists() or not quality_path.exists():
        run(settings)  # primeira execução: roda o pipeline completo
    fact = pd.read_csv(fact_path, dtype={"subgrupo_codigo": str, "grupo_codigo": str}, parse_dates=["data"])
    fact["regiao"] = pd.Categorical(fact["regiao"], categories=REGION_ORDER, ordered=True)
    o = settings.outliers
    # O modelo de "esperado" usa o conjunto completo; os filtros são aplicados depois.
    scored = outliers.detect_outliers(fact, float(o["z_threshold"]), int(o["min_admissions"]))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    return fact, scored, quality, settings.source_type == "synthetic"


def question(q: str, a: str | None = None) -> None:
    st.markdown(f'<div class="question">{q}</div>', unsafe_allow_html=True)
    if a:
        st.markdown(f'<div class="answer">{a}</div>', unsafe_allow_html=True)


try:
    fact, scored_all, quality, is_synthetic = load_data()
except Exception as exc:  # erro amigável em vez de stack trace
    st.error(f"Não foi possível carregar os dados: {exc}")
    st.info("Execute `python -m hcb.pipeline` na raiz do projeto e recarregue a página.")
    st.stop()

# --------------------------------------------------------------------------- filtros
with st.sidebar:
    st.header("Filtros")
    months = sorted(fact["competencia"].unique())
    start, end = st.select_slider("Período (competência)", options=months, value=(months[0], months[-1]))
    regions = st.multiselect("Região", REGION_ORDER, default=[], placeholder="Todas")
    uf_pool = sorted(fact.loc[fact["regiao"].isin(regions) if regions else slice(None), "uf_sigla"].unique())
    ufs = st.multiselect("UF", uf_pool, default=[], placeholder="Todas")
    groups = st.multiselect("Grupo de procedimento", sorted(fact["grupo_nome"].unique()), default=[],
                            placeholder="Todos")
    sg_pool = sorted(fact.loc[fact["grupo_nome"].isin(groups) if groups else slice(None), "subgrupo_nome"].unique())
    subgroups = st.multiselect("Subgrupo SIGTAP", sg_pool, default=[], placeholder="Todos")
    st.caption("Sem seleção = todos. Indicadores são recalculados sobre o recorte.")


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["competencia"].between(start, end)
    if regions:
        mask &= df["regiao"].isin(regions)
    if ufs:
        mask &= df["uf_sigla"].isin(ufs)
    if groups:
        mask &= df["grupo_nome"].isin(groups)
    if subgroups:
        mask &= df["subgrupo_nome"].isin(subgroups)
    return df[mask]


df = apply_filters(fact)
scored = apply_filters(scored_all)
if df.empty:
    st.warning("Nenhum dado para os filtros selecionados.")
    st.stop()

# --------------------------------------------------------------------------- cabeçalho
st.title("Health Cost Benchmark")
st.markdown(
    "Benchmark de **custos e economicidade de internações hospitalares** no modelo do SIH/SUS "
    "(AIH aprovadas por UF × mês × subgrupo SIGTAP). "
    + ('<span class="badge">BASE SINTÉTICA — números ilustrativos</span>' if is_synthetic else ""),
    unsafe_allow_html=True,
)

k = indicators.kpis(df)
n_out = int(scored["atipico"].sum())
c = st.columns(6)
c[0].metric("Valor aprovado", brl_compact(k["valor_total"]),
            help="Σ valor aprovado das AIH no recorte (R$ nominais).")
c[1].metric("Internações", number(k["internacoes"]), help="Σ AIH aprovadas.")
c[2].metric("Custo médio", brl(k["custo_medio_por_internacao"], 0),
            delta=pct(k["variacao_12m_custo_medio"], signed=True) + " em 12m"
            if pd.notna(k["variacao_12m_custo_medio"]) else None, delta_color="inverse",
            help="Custo médio por internação: média ponderada = Σ valor ÷ Σ internações. "
                 "Delta: últimos 12 meses vs. 12 anteriores.")
c[3].metric("Mediana ponderada", brl(k["custo_mediano_ponderado"], 0),
            help="Custo por internação da célula que contém a internação mediana. Menos sensível a "
                 "procedimentos de alto custo.")
c[4].metric("Custo por dia", brl(k["custo_por_dia"], 0),
            help=f"Σ valor ÷ Σ dias de permanência. Permanência média: {number(k['permanencia_media'], 1)} dias.")
c[5].metric("Células atípicas", number(n_out), help="Competência × UF × subgrupo com |z robusto| > 3,5.")

tabs = st.tabs(["📈 Evolução", "📊 Distribuição", "🗺️ Regiões e UFs", "🧮 Concentração",
                "🚩 Atípicos", "📋 Dados", "✅ Qualidade", "ℹ️ Metodologia", "🤖 Pergunte aos dados"])

# --------------------------------------------------------------------------- evolução
with tabs[0]:
    metric_label = st.radio("Métrica", ["Custo médio por internação", "Valor total", "Internações"],
                            horizontal=True)
    metric = {"Custo médio por internação": "custo_medio_por_internacao", "Valor total": "valor_total",
              "Internações": "internacoes"}[metric_label]
    split = st.toggle("Separar por região", value=True)
    series = indicators.monthly(df, "regiao" if split else None)
    tr = statistics.trends_by(df, "regiao") if split else None
    total_tr = statistics.trend(indicators.monthly(df).set_index("data")["custo_medio_por_internacao"])
    question(f"Como {metric_label.lower()} evolui ao longo do tempo?",
             "Crescimento anual estimado do custo médio no recorte: "
             f"<b>{pct(total_tr['crescimento_anual'], signed=True)}</b> "
             f"(Theil–Sen; IC95% {pct(total_tr['ic95_inf'])} a {pct(total_tr['ic95_sup'])}). "
             "Valores nominais — parte do crescimento reflete inflação e reajustes de tabela.")
    st.plotly_chart(charts.time_series(series, metric, metric_label, "regiao" if split else None,
                                       money=metric != "internacoes"), width="stretch")
    col1, col2 = st.columns([3, 2])
    with col1:
        question("O custo médio está acelerando ou desacelerando?",
                 "Variação de cada mês contra o mesmo mês do ano anterior (remove sazonalidade).")
        st.plotly_chart(charts.yoy_bars(indicators.monthly(df)), width="stretch")
    with col2:
        if tr is not None and not tr.empty:
            question("A tendência é estatisticamente consistente por região?")
            st.dataframe(
                tr[["regiao", "crescimento_anual", "ic95_inf", "ic95_sup", "p_ajustado_holm", "tendencia"]],
                hide_index=True, width="stretch",
                column_config={
                    "regiao": "Região",
                    "crescimento_anual": st.column_config.NumberColumn("Cresc. anual", format="percent"),
                    "ic95_inf": st.column_config.NumberColumn("IC95% inf.", format="percent"),
                    "ic95_sup": st.column_config.NumberColumn("IC95% sup.", format="percent"),
                    "p_ajustado_holm": st.column_config.NumberColumn("p (Holm)", format="%.2e"),
                    "tendencia": "Leitura",
                },
            )

# --------------------------------------------------------------------------- distribuição
with tabs[1]:
    question("Como se distribui o custo por internação dentro de cada subgrupo?",
             "Cada observação é uma célula UF × mês. Caixas largas indicam grande heterogeneidade de custo "
             "entre UFs/meses; pontos isolados estão além de 1,5 × IQR (Tukey, escala log).")
    st.plotly_chart(charts.box_by_subgroup(df), width="stretch")
    sg_sel = st.selectbox("Detalhar subgrupo", sorted(df["subgrupo_nome"].unique()))
    question(f"Qual o formato da distribuição em “{sg_sel}”?")
    st.plotly_chart(charts.histogram(df, sg_sel), width="stretch")
    question("Quais subgrupos apresentam maior variação de custo entre UFs?",
             "CV = desvio-padrão ÷ média do custo médio das UFs (UFs com ≥ 30 internações no período).")
    var = statistics.variation_between_ufs(df)
    st.dataframe(
        var[["subgrupo_nome", "ufs_avaliadas", "cv_entre_ufs", "razao_p90_p10", "uf_menor_custo", "menor_custo",
             "uf_maior_custo", "maior_custo"]],
        hide_index=True, width="stretch",
        column_config={
            "subgrupo_nome": "Subgrupo", "ufs_avaliadas": "UFs",
            "cv_entre_ufs": st.column_config.ProgressColumn("CV entre UFs", format="percent", min_value=0,
                                                            max_value=float(max(var["cv_entre_ufs"].max(), 0.01))),
            "razao_p90_p10": st.column_config.NumberColumn("P90/P10", format="%.2f"),
            "uf_menor_custo": "UF menor", "menor_custo": st.column_config.NumberColumn("Menor", format="R$ %.0f"),
            "uf_maior_custo": "UF maior", "maior_custo": st.column_config.NumberColumn("Maior", format="R$ %.0f"),
        },
    )

# --------------------------------------------------------------------------- regiões
with tabs[2]:
    mix = indicators.mix_adjusted_index(df, "uf_sigla").merge(
        df[["uf_sigla", "regiao"]].drop_duplicates(), on="uf_sigla")
    question("Quais UFs gastam mais do que o esperado para o seu mix de procedimentos?",
             "Índice = custo observado ÷ custo esperado se cada internação custasse a média nacional do seu "
             "subgrupo no mesmo mês (padronização indireta). Remove o efeito de UFs fazerem procedimentos "
             "mais caros; não controla gravidade dentro do subgrupo.")
    st.plotly_chart(charts.mix_index_bars(mix), width="stretch")

    col1, col2 = st.columns(2)
    with col1:
        question("Como as regiões se comparam?")
        reg = indicators.summarize(df, "regiao").merge(indicators.utilization_rate(df, "regiao"), on="regiao")
        reg = reg.merge(indicators.mix_adjusted_index(df, "regiao")[["regiao", "indice_custo_ajustado"]],
                        on="regiao")
        st.dataframe(
            reg[["regiao", "valor_total", "participacao_valor", "internacoes", "custo_medio_por_internacao",
                 "indice_custo_ajustado", "internacoes_por_10mil_hab_mes"]],
            hide_index=True, width="stretch",
            column_config={
                "regiao": "Região",
                "valor_total": st.column_config.NumberColumn("Valor total", format="compact"),
                "participacao_valor": st.column_config.NumberColumn("Part.", format="percent"),
                "internacoes": st.column_config.NumberColumn("Internações", format="localized"),
                "custo_medio_por_internacao": st.column_config.NumberColumn("Custo médio", format="R$ %.2f"),
                "indice_custo_ajustado": st.column_config.NumberColumn("Índice mix", format="%.3f"),
                "internacoes_por_10mil_hab_mes": st.column_config.NumberColumn("Intern./10 mil hab./mês",
                                                                               format="%.1f"),
            },
        )
    with col2:
        sg_pick = st.selectbox("Subgrupo para comparar UFs", sorted(df["subgrupo_nome"].unique()), key="sg_uf")
        question("UFs com maior volume têm custo médio diferente?",
                 "Associação descritiva (não causal): volume pode refletir porte da rede, perfil de casos "
                 "e referência de pacientes de outras UFs.")
        per_uf = indicators.summarize(df[df["subgrupo_nome"] == sg_pick], ["uf_sigla", "regiao"])
        st.plotly_chart(charts.volume_cost_scatter(per_uf), width="stretch")
    regional = statistics.regional_differences(df)
    n_sig = int(regional["diferenca_significativa"].sum())
    question("As diferenças regionais são estatisticamente relevantes?",
             f"Kruskal–Wallis por subgrupo (unidade = UF): <b>{n_sig} de {len(regional)}</b> subgrupos com "
             "diferença significativa após correção de Holm. ε² mede a magnitude.")
    st.dataframe(
        regional[["subgrupo_nome", "ufs", "epsilon2", "magnitude_efeito", "p_ajustado_holm",
                  "regiao_maior_mediana", "regiao_menor_mediana"]],
        hide_index=True, width="stretch",
        column_config={"subgrupo_nome": st.column_config.TextColumn("Subgrupo", width="large"), "ufs": "UFs",
                       "epsilon2": st.column_config.NumberColumn("ε²", format="%.2f"),
                       "magnitude_efeito": "Efeito",
                       "p_ajustado_holm": st.column_config.NumberColumn("p (Holm)", format="%.3f"),
                       "regiao_maior_mediana": "Maior mediana", "regiao_menor_mediana": "Menor mediana"},
    )

# --------------------------------------------------------------------------- concentração
with tabs[3]:
    table, summ = indicators.concentration(df, "subgrupo_nome", 0.8)
    question("Quais subgrupos concentram o volume financeiro?",
             f"<b>{summ['itens_para_participacao_alvo']} de {summ['itens']}</b> subgrupos (em azul) respondem por "
             f"80% do valor. HHI = {number(summ['hhi'])} (acima de 1.500 indica concentração moderada; "
             "acima de 2.500, alta).")
    st.plotly_chart(charts.pareto_bars(table), width="stretch")
    question("Onde o gasto é alto por volume e onde é alto por custo unitário?")
    sg_tab = indicators.summarize(df, ["grupo_nome", "subgrupo_nome"])
    st.dataframe(
        sg_tab[["subgrupo_nome", "grupo_nome", "valor_total", "participacao_valor", "internacoes",
                "custo_medio_por_internacao", "custo_mediano_celula", "permanencia_media", "custo_por_dia"]],
        hide_index=True, width="stretch",
        column_config={
            "subgrupo_nome": "Subgrupo", "grupo_nome": "Grupo",
            "valor_total": st.column_config.NumberColumn("Valor total", format="compact"),
            "participacao_valor": st.column_config.NumberColumn("Part.", format="percent"),
            "internacoes": st.column_config.NumberColumn("Internações", format="localized"),
            "custo_medio_por_internacao": st.column_config.NumberColumn("Custo médio", format="R$ %.0f"),
            "custo_mediano_celula": st.column_config.NumberColumn("Mediana (células)", format="R$ %.0f"),
            "permanencia_media": st.column_config.NumberColumn("Perm. média (dias)", format="%.1f"),
            "custo_por_dia": st.column_config.NumberColumn("Custo/dia", format="R$ %.0f"),
        },
    )

# --------------------------------------------------------------------------- atípicos
with tabs[4]:
    thr = st.slider("Limiar do |z robusto|", 2.5, 8.0, 3.5, 0.5,
                    help="3,5 é o limiar usual para escore robusto (Iglewicz & Hoaglin).")
    sc = scored.copy()
    sc["atipico"] = sc["z_robusto"].abs() > thr
    flagged = outliers.outlier_table(sc)
    above = flagged[flagged["z_robusto"] > 0]
    excess = (above["valor_total"] - above["custo_esperado"] * above["qtd_internacoes"]).sum()
    question("Quais registros fogem do padrão esperado?",
             f"<b>{len(flagged)}</b> células atípicas no recorte; {len(above)} acima do esperado, com excesso "
             f"estimado de <b>{brl_compact(excess)}</b>. O esperado considera o mesmo subgrupo e UF, ajustado ao "
             "nível nacional do mês; o limiar considera o tamanho da célula (funnel plot).")
    st.plotly_chart(charts.outlier_scatter(sc, thr), width="stretch")
    st.caption("Atipicidade é um sinal para priorizar auditoria e verificação de registro — não comprova erro, "
               "fraude ou ineficiência.")
    st.dataframe(
        flagged, hide_index=True, width="stretch",
        column_config={
            "competencia": "Competência", "uf_sigla": "UF", "regiao": "Região", "subgrupo_codigo": "Cód.",
            "subgrupo_nome": "Subgrupo",
            "qtd_internacoes": st.column_config.NumberColumn("Internações", format="localized"),
            "valor_total": st.column_config.NumberColumn("Valor", format="compact"),
            "custo_por_internacao": st.column_config.NumberColumn("Custo/intern.", format="R$ %.0f"),
            "custo_esperado": st.column_config.NumberColumn("Esperado", format="R$ %.0f"),
            "z_robusto": st.column_config.NumberColumn("z", format="%.1f"),
            "direcao_atipicidade": "Direção",
            "excesso_estimado": st.column_config.NumberColumn("Excesso estimado", format="compact"),
        },
    )

# --------------------------------------------------------------------------- dados
with tabs[5]:
    question("Tabela detalhada do recorte", f"{number(len(df))} linhas (competência × UF × subgrupo).")
    cols = ["competencia", "regiao", "uf_sigla", "grupo_nome", "subgrupo_codigo", "subgrupo_nome",
            "qtd_internacoes", "valor_total", "dias_permanencia", "custo_por_internacao", "custo_por_dia",
            "permanencia_media"]
    st.dataframe(
        df[cols], hide_index=True, width="stretch", height=480,
        column_config={
            "competencia": "Competência", "regiao": "Região", "uf_sigla": "UF", "grupo_nome": "Grupo",
            "subgrupo_codigo": "Cód.", "subgrupo_nome": "Subgrupo",
            "qtd_internacoes": st.column_config.NumberColumn("Internações", format="localized"),
            "valor_total": st.column_config.NumberColumn("Valor total", format="R$ %.2f"),
            "dias_permanencia": st.column_config.NumberColumn("Dias", format="localized"),
            "custo_por_internacao": st.column_config.NumberColumn("Custo/intern.", format="R$ %.2f"),
            "custo_por_dia": st.column_config.NumberColumn("Custo/dia", format="R$ %.2f"),
            "permanencia_media": st.column_config.NumberColumn("Perm. média", format="%.2f"),
        },
    )
    st.download_button("Baixar recorte (CSV)", df[cols].to_csv(index=False).encode("utf-8"),
                       file_name="health_cost_benchmark_recorte.csv", mime="text/csv")

# --------------------------------------------------------------------------- qualidade
with tabs[6]:
    question(f"Os dados são confiáveis para análise? Status: {quality['status']}",
             f"{number(quality['rows_received'])} linhas recebidas · {number(quality['rows_approved'])} aprovadas · "
             f"{number(quality['rows_quarantined'])} em quarentena ({pct(quality['rejected_ratio'], 2)}). "
             "Linhas com erro não entram em nenhum indicador; alertas são mantidos e sinalizados.")
    rules = pd.DataFrame(quality["rules"]).drop(columns=["examples"])
    rules["resultado"] = rules["failed_rows"].map(lambda n: "✅ ok" if n == 0 else f"⚠️ {n} linha(s)")
    st.dataframe(rules[["name", "description", "severity", "resultado"]], hide_index=True, width="stretch",
                 column_config={"name": "Regra", "description": "Descrição", "severity": "Severidade",
                                "resultado": "Resultado"})
    checks = pd.DataFrame(quality["dataset_checks"])
    checks["passed"] = checks["passed"].map({True: "✅ ok", False: "⚠️ falhou"})
    st.dataframe(checks[["name", "description", "severity", "passed", "detail"]], hide_index=True,
                 width="stretch",
                 column_config={"name": "Verificação", "description": "Descrição", "severity": "Severidade",
                                "passed": "Resultado", "detail": "Detalhe"})

# --------------------------------------------------------------------------- metodologia
with tabs[7]:
    st.markdown(
        """
**Unidade de análise:** competência (mês) × UF de internação × subgrupo SIGTAP. Sem dados individuais.

| Indicador | Definição |
|---|---|
| Custo médio por internação | Σ valor aprovado ÷ Σ internações (média ponderada — não é média de médias) |
| Mediana ponderada | Custo por internação da célula que contém a internação mediana |
| Custo por dia | Σ valor ÷ Σ dias de permanência |
| Variação 12 meses | Custo médio dos últimos 12 meses ÷ 12 meses anteriores − 1 |
| Crescimento anual | Theil–Sen sobre log(custo médio mensal), anualizado; Mann–Kendall para significância |
| CV entre UFs | Desvio-padrão ÷ média do custo médio das UFs (≥ 30 internações) |
| Índice ajustado ao mix | Observado ÷ esperado com custo nacional do subgrupo no mês (padronização indireta) |
| Diferença regional | Kruskal–Wallis por subgrupo (unidade = UF), ε², correção de Holm |
| Concentração | Participação, núcleo de Pareto (80%) e HHI |
| Atipicidade | z robusto do resíduo log vs. esperado (subgrupo × UF × mês), variância a/n + b |

**Limites de interpretação:** valores nominais (sem deflação), apenas produção aprovada do SUS (não inclui
saúde suplementar nem custos não faturados via AIH), diferenças entre regiões são associações e podem refletir
perfil de casos, complexidade da rede ou registro. Correlação não implica causalidade.

Documentação completa: `docs/methodology.md` e `docs/data_sources.md`.
        """
    )

# --------------------------------------------------------------------------- agente de IA
EXAMPLES = [
    "O que explica o aumento do gasto entre 2023 e 2024: volume, mix ou custo unitário?",
    "Quais UFs gastam mais do que o esperado para o seu mix de procedimentos?",
    "Quais atípicos de cirurgia do aparelho circulatório devo auditar primeiro?",
    "A tendência de custo é diferente entre as regiões?",
]


@st.cache_resource(show_spinner=False)
def get_agent() -> HealthCostAgent:
    settings = load_settings()
    data, _, _, synthetic = load_data()
    return HealthCostAgent(data, synthetic=synthetic, audit_log=settings.reports_dir / "agent_audit.jsonl")


def render_turn(question: str, result) -> None:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        st.markdown(result.answer)
        if result.ungrounded:
            st.warning("⚠️ Números sem correspondência nos resultados das ferramentas (verifique): "
                       + ", ".join(result.ungrounded))
        label = f"Como cheguei a esta resposta — {len(result.tool_calls)} consulta(s) aos dados"
        with st.expander(label):
            st.caption("✅ Todos os números conferem com as ferramentas." if result.grounded else
                       "Alguns números não foram encontrados nas saídas das ferramentas.")
            for call in result.tool_calls:
                status = "✅" if call.ok else "❌"
                st.markdown(f"{status} `{call.name}` · {call.duration_ms} ms")
                st.code(json.dumps(call.input, ensure_ascii=False, indent=2), language="json")
                if call.error:
                    st.caption(f"Erro devolvido ao modelo: {call.error}")
            st.caption(f"Modelo: {result.model} · etapas: {result.steps} · tokens de entrada: "
                       f"{number(result.usage['input_tokens'])} (cache: "
                       f"{number(result.usage['cache_read_input_tokens'])}) · saída: "
                       f"{number(result.usage['output_tokens'])}")


with tabs[8]:
    question("Pergunte aos dados em linguagem natural",
             "Um agente de IA (Claude) consulta as mesmas funções testadas do pipeline e responde citando os "
             "números retornados. Cada resposta mostra as consultas feitas e verifica se todos os números "
             "vieram dos dados. Os filtros da barra lateral não se aplicam aqui: o agente usa a base completa "
             "e declara os recortes que escolheu.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.info("Para usar o agente, defina a variável de ambiente `ANTHROPIC_API_KEY` antes de iniciar o "
                "Streamlit (ou faça `ant auth login`). Veja `docs/ai_agent.md`. Nenhuma chave é armazenada "
                "no projeto.")
    st.session_state.setdefault("agent_conv", Conversation())
    st.session_state.setdefault("agent_turns", [])

    cols = st.columns(len(EXAMPLES))
    clicked = None
    for col, example in zip(cols, EXAMPLES, strict=True):
        if col.button(example, width="stretch"):
            clicked = example
    for q, r in st.session_state["agent_turns"]:
        render_turn(q, r)

    typed = st.chat_input("Ex.: Qual região teve maior crescimento do custo médio?")
    prompt = typed or clicked
    if prompt:
        with st.spinner("Consultando os dados…"):
            try:
                res = get_agent().ask(prompt, st.session_state["agent_conv"])
            except AgentError as exc:
                st.error(str(exc))
            else:
                st.session_state["agent_turns"].append((prompt, res))
                render_turn(prompt, res)
    if st.session_state["agent_turns"] and st.button("Nova conversa"):
        st.session_state["agent_conv"] = Conversation()
        st.session_state["agent_turns"] = []
        st.rerun()
