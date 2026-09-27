from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hcb.config import PROJECT_ROOT
from hcb.ingestion import synthetic
from hcb.processing.cleaning import clean
from hcb.processing.transform import transform

REF = PROJECT_ROOT / "data" / "reference"


@pytest.fixture(scope="session")
def ufs() -> pd.DataFrame:
    return pd.read_csv(REF / "ufs.csv", dtype={"uf_codigo_ibge": str})


@pytest.fixture(scope="session")
def subgroups() -> pd.DataFrame:
    return pd.read_csv(REF / "subgrupos_sigtap.csv", dtype=str)


@pytest.fixture(scope="session")
def synthetic_result(ufs):
    return synthetic.generate(ufs, start="2022-01", end="2023-12", seed=7)


@pytest.fixture(scope="session")
def clean_fact(ufs, subgroups) -> pd.DataFrame:
    """Tabela fato sem problemas de qualidade injetados (24 meses)."""
    result = synthetic.generate(ufs, start="2022-01", end="2023-12", seed=11,
                                inject_quality_issues=False, inject_anomalies=False)
    cleaned, _ = clean(result.data.astype(str))
    return transform(cleaned, ufs, subgroups)


def make_raw(rows: list[dict]) -> pd.DataFrame:
    base = {"competencia": "2023-01", "uf_sigla": "SP", "subgrupo_codigo": "0310",
            "qtd_internacoes": "100", "valor_total": "80000.00", "dias_permanencia": "220"}
    return pd.DataFrame([{**base, **r} for r in rows]).astype(str)


@pytest.fixture
def raw_factory():
    return make_raw


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
