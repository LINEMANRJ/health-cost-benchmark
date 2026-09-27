"""Etapa de ingestão: obtém os dados brutos conforme a fonte configurada."""
from __future__ import annotations

import logging

import pandas as pd

from hcb.config import Settings
from hcb.ingestion import synthetic
from hcb.schema import RAW_COLUMNS

log = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """Falha ao obter ou ler os dados brutos."""


def load_reference(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carrega as tabelas de referência (UFs e subgrupos SIGTAP)."""
    try:
        ufs = pd.read_csv(settings.ufs_file, dtype={"uf_codigo_ibge": str})
        subgroups = pd.read_csv(settings.subgroups_file, dtype=str)
    except FileNotFoundError as exc:
        raise IngestionError(f"Tabela de referência não encontrada: {exc.filename}") from exc
    return ufs, subgroups


def ingest(settings: Settings, ufs: pd.DataFrame, regenerate: bool = False) -> pd.DataFrame:
    """Retorna o DataFrame bruto (todas as colunas como texto, sem tratamento)."""
    raw_file = settings.raw_file
    if settings.source_type == "synthetic" and (regenerate or not raw_file.exists()):
        opts = settings.synthetic
        log.info("Gerando base sintética em %s", raw_file)
        result = synthetic.generate(
            ufs,
            start=opts.get("start", "2022-01"),
            end=opts.get("end", "2024-12"),
            seed=int(opts.get("seed", 42)),
            inject_quality_issues=bool(opts.get("inject_quality_issues", True)),
            inject_anomalies=bool(opts.get("inject_anomalies", True)),
        )
        synthetic.write(result, raw_file)

    if not raw_file.exists():
        raise IngestionError(
            f"Arquivo bruto não encontrado: {raw_file}. "
            "Para source.type=contract_csv, gere o arquivo conforme docs/data_sources.md."
        )
    try:
        raw = pd.read_csv(raw_file, dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise IngestionError(f"Não foi possível ler {raw_file}: {exc}") from exc

    missing = [c for c in RAW_COLUMNS if c not in raw.columns]
    if missing:
        raise IngestionError(f"Colunas obrigatórias ausentes no arquivo bruto: {missing}")
    log.info("Ingestão: %d linhas lidas de %s", len(raw), raw_file.name)
    return raw
