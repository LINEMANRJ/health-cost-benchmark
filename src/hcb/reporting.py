"""Geração do resumo analítico (reports/analysis_summary.md) a partir das saídas do pipeline."""
from __future__ import annotations

import pandas as pd

from hcb.formatting import brl, brl_compact, number, pct
from hcb.processing.validation import QualityReport


def build_summary(
    *,
    kpis: dict,
    quality: QualityReport,
    by_region: pd.DataFrame,
    by_uf: pd.DataFrame,
    by_sg: pd.DataFrame,
    conc_summary: dict,
    trends_sg: pd.DataFrame,
    trends_rg: pd.DataFrame,
    variation: pd.DataFrame,
    regional: pd.DataFrame,
    outlier_rows: pd.DataFrame,
    synthetic: bool,
) -> str:
    lines: list[str] = ["# Resumo analítico — Health Cost Benchmark", ""]
    if synthetic:
        lines += [
            "> ⚠️ **Resultados gerados sobre base SINTÉTICA.** Os números ilustram o funcionamento do",
            "> pipeline e dos métodos; não descrevem a realidade do SUS.",
            "",
        ]

    lines += [
        "## Visão geral",
        "",
        f"- Período: **{kpis['periodo_inicio']} a {kpis['periodo_fim']}** ({kpis['meses']} meses)",
        f"- Valor total aprovado: **{brl_compact(kpis['valor_total'])}**",
        f"- Internações: **{number(kpis['internacoes'])}**",
        f"- Custo médio por internação: **{brl(kpis['custo_medio_por_internacao'])}**"
        f" (mediana ponderada {brl(kpis['custo_mediano_ponderado'])})",
        f"- Custo por dia de permanência: **{brl(kpis['custo_por_dia'])}**;"
        f" permanência média {number(kpis['permanencia_media'], 1)} dias",
        f"- Variação do custo médio (últimos 12 meses vs. 12 anteriores):"
        f" **{pct(kpis['variacao_12m_custo_medio'], signed=True)}**",
        f"- Qualidade dos dados: **{quality.status}** — {number(quality.rows_quarantined)} linhas em quarentena"
        f" ({pct(quality.rejected_ratio, 2)})",
        "",
    ]

    # 1. Evolução temporal
    lines += ["## 1. Como os custos evoluem ao longo do tempo?", ""]
    if not trends_rg.empty:
        lines += ["| Região | Crescimento anual (Theil–Sen) | IC 95% | p ajustado | Leitura |",
                  "|---|---:|---|---:|---|"]
        for r in trends_rg.itertuples():
            lines.append(f"| {r.regiao} | {pct(r.crescimento_anual, signed=True)} | "
                         f"{pct(r.ic95_inf)} a {pct(r.ic95_sup)} | {r.p_ajustado_holm:.3g} | {r.tendencia} |")
    top_up = trends_sg.head(3)
    lines += ["", "Subgrupos com maior crescimento anual do custo médio: " + "; ".join(
        f"{r.subgrupo_nome} ({pct(r.crescimento_anual, signed=True)})" for r in top_up.itertuples()) + ".", ""]

    # 2. Variação entre categorias
    lines += ["## 2. Quais categorias apresentam maior variação?", "",
              "Coeficiente de variação (CV) do custo médio por internação entre UFs, por subgrupo:", "",
              "| Subgrupo | UFs | CV entre UFs | Razão P90/P10 | Menor custo | Maior custo |",
              "|---|---:|---:|---:|---|---|"]
    for r in variation.head(5).itertuples():
        lines.append(f"| {r.subgrupo_nome} | {r.ufs_avaliadas} | {pct(r.cv_entre_ufs)} | "
                     f"{number(r.razao_p90_p10, 2)} | {r.uf_menor_custo} ({brl(r.menor_custo, 0)}) | "
                     f"{r.uf_maior_custo} ({brl(r.maior_custo, 0)}) |")
    lines.append("")

    # 3. Outliers
    n_out = len(outlier_rows)
    lines += ["## 3. Existem valores atípicos?", "",
              f"Foram sinalizadas **{n_out} células** (competência × UF × subgrupo) com |z robusto| acima do limiar."]
    if n_out:
        above = outlier_rows[outlier_rows["direcao_atipicidade"] == "acima do esperado"]
        lines += [f"{len(above)} estão acima do esperado, somando excesso estimado de "
                  f"**{brl_compact(above['excesso_estimado'].sum())}** em relação ao custo esperado.", "",
                  "| Competência | UF | Subgrupo | Internações | Custo/internação | Esperado | z |",
                  "|---|---|---|---:|---:|---:|---:|"]
        for r in outlier_rows.head(8).itertuples():
            lines.append(f"| {r.competencia} | {r.uf_sigla} | {r.subgrupo_nome} | {number(r.qtd_internacoes)} | "
                         f"{brl(r.custo_por_internacao, 0)} | {brl(r.custo_esperado, 0)} | {r.z_robusto:.1f} |")
    lines += ["", "Atipicidade indica prioridade de auditoria/investigação, não erro ou irregularidade comprovada.", ""]

    # 4. Diferenças regionais
    sig = regional[regional["diferenca_significativa"]]
    lines += ["## 4. Existem diferenças relevantes entre regiões?", "",
              "| Região | Custo médio/internação | Índice ajustado ao mix "
              "| Internações/10 mil hab./mês | Participação no valor |",
              "|---|---:|---:|---:|---:|"]
    for r in by_region.sort_values("indice_custo_ajustado", ascending=False).itertuples():
        lines.append(f"| {r.regiao} | {brl(r.custo_medio_por_internacao)} | {number(r.indice_custo_ajustado, 3)} | "
                     f"{number(r.internacoes_por_10mil_hab_mes, 1)} | {pct(r.participacao_valor)} |")
    lines += ["", f"Kruskal–Wallis por subgrupo (UFs agrupadas por região): diferença significativa após Holm em "
              f"**{len(sig)} de {len(regional)}** subgrupos."]
    if len(sig):
        lines.append("Maiores efeitos: " + "; ".join(
            f"{r.subgrupo_nome} (ε² = {number(r.epsilon2, 2)}, {r.magnitude_efeito}; "
            f"maior mediana: {r.regiao_maior_mediana})"
            for r in sig.head(3).itertuples()) + ".")
    lines += ["", "Diferenças observadas são associações: podem refletir mix de casos dentro do subgrupo, "
              "complexidade da rede, incentivos/tabelas complementares ou registro, e não indicam por si só "
              "ineficiência.", ""]

    # 5. Concentração
    lines += ["## 5. Quais grupos concentram maior volume financeiro?", "",
              f"{conc_summary['itens_para_participacao_alvo']} de {conc_summary['itens']} subgrupos concentram "
              f"{pct(conc_summary['participacao_alvo'], 0)} do valor total (HHI = {number(conc_summary['hhi'])}).", "",
              "| Subgrupo | Valor total | Participação | Internações | Custo médio |", "|---|---:|---:|---:|---:|"]
    for r in by_sg.head(6).itertuples():
        lines.append(f"| {r.subgrupo_nome} | {brl_compact(r.valor_total)} | {pct(r.participacao_valor)} | "
                     f"{number(r.internacoes)} | {brl(r.custo_medio_por_internacao)} |")
    top_uf = by_uf.head(3)
    lines += ["", "UFs com maior valor total: " + ", ".join(
        f"{r.uf_sigla} ({pct(r.participacao_valor)})" for r in top_uf.itertuples()) + ".", ""]
    return "\n".join(lines)
