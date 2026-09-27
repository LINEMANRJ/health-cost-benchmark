"""Orquestração: bruto → tratamento → validação → transformação → indicadores → análise.

Uso:
    python -m hcb.pipeline                # usa config/settings.yaml
    python -m hcb.pipeline --regenerate   # regera a base sintética
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from hcb.analysis import indicators, outliers, statistics
from hcb.config import ConfigError, Settings, load_settings
from hcb.ingestion.loader import IngestionError, ingest, load_reference
from hcb.processing.cleaning import clean
from hcb.processing.transform import TransformError, transform
from hcb.processing.validation import DataQualityError, QualityReport, report_to_markdown, validate
from hcb.reporting import build_summary

log = logging.getLogger("hcb.pipeline")

FACT_FILE = "fato_internacoes.csv"
SCORED_FILE = "fato_internacoes_com_atipicidade.csv"


@dataclass
class PipelineResult:
    fact: pd.DataFrame
    scored: pd.DataFrame
    quality: QualityReport
    outputs: dict[str, Path]


def _save(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def run(settings: Settings, regenerate: bool = False) -> PipelineResult:
    t0 = time.perf_counter()
    processed, reports = settings.processed_dir, settings.reports_dir
    ind_dir = processed / "indicadores"
    outputs: dict[str, Path] = {}

    # 1. Ingestão
    ufs, subgroups = load_reference(settings)
    raw = ingest(settings, ufs, regenerate=regenerate)

    # 2. Tratamento
    cleaned, cstats = clean(raw)
    log.info("Tratamento: %d duplicatas exatas removidas", cstats.exact_duplicates_removed)

    # 3. Validação
    q = settings.quality
    approved, quarantine, quality = validate(
        cleaned, set(ufs["uf_sigla"]), set(subgroups["subgrupo_codigo"]),
        max_rejected_ratio=float(q["max_rejected_ratio"]), min_months=int(q["min_months"]),
    )
    quality.save(reports / "quality_report.json")
    (reports / "quality_report.md").write_text(report_to_markdown(quality), encoding="utf-8")
    outputs["quarentena"] = _save(quarantine, processed / "quarentena.csv")
    log.info("Validação: %s — %d aprovadas, %d em quarentena", quality.status, len(approved), len(quarantine))

    # 4. Transformação
    fact = transform(approved, ufs, subgroups)
    outputs["fato"] = _save(fact, processed / FACT_FILE)

    # 5. Indicadores
    a = settings.analysis
    kpis = indicators.kpis(fact)
    outputs["kpis"] = ind_dir / "kpis.json"
    outputs["kpis"].parent.mkdir(parents=True, exist_ok=True)
    outputs["kpis"].write_text(json.dumps(kpis, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["mensal"] = _save(indicators.monthly(fact), ind_dir / "serie_mensal.csv")
    outputs["mensal_regiao"] = _save(indicators.monthly(fact, "regiao"), ind_dir / "serie_mensal_regiao.csv")
    by_region = indicators.summarize(fact, "regiao").merge(indicators.utilization_rate(fact, "regiao"), on="regiao")
    by_region = by_region.merge(indicators.mix_adjusted_index(fact, "regiao")[["regiao", "indice_custo_ajustado"]],
                                on="regiao")
    outputs["regiao"] = _save(by_region, ind_dir / "por_regiao.csv")
    by_uf = indicators.summarize(fact, ["uf_sigla", "regiao"]).merge(
        indicators.utilization_rate(fact, "uf_sigla"), on="uf_sigla")
    by_uf = by_uf.merge(indicators.mix_adjusted_index(fact, "uf_sigla")[["uf_sigla", "indice_custo_ajustado"]],
                        on="uf_sigla")
    outputs["uf"] = _save(by_uf, ind_dir / "por_uf.csv")
    by_sg = indicators.summarize(fact, ["grupo_nome", "subgrupo_codigo", "subgrupo_nome"])
    outputs["subgrupo"] = _save(by_sg, ind_dir / "por_subgrupo.csv")
    conc_table, conc_summary = indicators.concentration(fact, "subgrupo_nome", float(a["pareto_share"]))
    outputs["concentracao"] = _save(conc_table, ind_dir / "concentracao_subgrupos.csv")

    # 6. Análise estatística e atipicidade
    alpha = float(a["alpha"])
    trends_sg = statistics.trends_by(fact, "subgrupo_nome", alpha)
    trends_rg = statistics.trends_by(fact, "regiao", alpha)
    variation = statistics.variation_between_ufs(fact)
    regional = statistics.regional_differences(fact, alpha)
    spearman = statistics.spearman_volume_cost(fact)
    outputs["tendencia_subgrupo"] = _save(trends_sg, ind_dir / "tendencia_por_subgrupo.csv")
    outputs["tendencia_regiao"] = _save(trends_rg, ind_dir / "tendencia_por_regiao.csv")
    outputs["variacao"] = _save(variation, ind_dir / "variacao_entre_ufs.csv")
    outputs["regional"] = _save(regional, ind_dir / "diferencas_regionais.csv")
    outputs["spearman"] = _save(spearman, ind_dir / "associacao_volume_custo.csv")

    o = settings.outliers
    scored = outliers.detect_outliers(fact, float(o["z_threshold"]), int(o["min_admissions"]))
    outputs["atipicos"] = _save(outliers.outlier_table(scored), ind_dir / "atipicos.csv")
    outputs["fato_atipicidade"] = _save(scored, processed / SCORED_FILE)

    # 7. Relatório analítico
    summary = build_summary(
        kpis=kpis, quality=quality, by_region=by_region, by_uf=by_uf, by_sg=by_sg,
        conc_summary=conc_summary, trends_sg=trends_sg, trends_rg=trends_rg, variation=variation,
        regional=regional, outlier_rows=outliers.outlier_table(scored), synthetic=settings.source_type == "synthetic",
    )
    outputs["resumo"] = reports / "analysis_summary.md"
    outputs["resumo"].write_text(summary, encoding="utf-8")

    log.info("Pipeline concluído em %.1fs — saídas em %s", time.perf_counter() - t0, processed)
    return PipelineResult(fact=fact, scored=scored, quality=quality, outputs=outputs)


def load_fact(settings: Settings) -> pd.DataFrame:
    """Lê a tabela fato processada (executa o pipeline se ela ainda não existir)."""
    from hcb.schema import REGION_ORDER

    path = settings.processed_dir / FACT_FILE
    if not path.exists():
        run(settings)
    fact = pd.read_csv(path, dtype={"subgrupo_codigo": str, "grupo_codigo": str}, parse_dates=["data"])
    fact["regiao"] = pd.Categorical(fact["regiao"], categories=REGION_ORDER, ordered=True)
    return fact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Executa o pipeline do Health Cost Benchmark.")
    parser.add_argument("--config", type=Path, default=None, help="Caminho do settings.yaml")
    parser.add_argument("--regenerate", action="store_true", help="Regera a base sintética")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    try:
        result = run(load_settings(args.config), regenerate=args.regenerate)
    except (ConfigError, IngestionError, DataQualityError, TransformError) as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 1
    print(f"\nStatus de qualidade: {result.quality.status}")
    for name, path in result.outputs.items():
        print(f"  {name:<20} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
