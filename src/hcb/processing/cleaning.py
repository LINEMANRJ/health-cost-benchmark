"""Etapa de tratamento: padronização de formatos e tipos, sem descartar informação.

Valores que não puderem ser convertidos viram nulos e são tratados pela validação,
que decide o que é rejeitado (quarentena) — a limpeza nunca "conserta" um valor
inventando dados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from hcb.schema import KEY_COLUMNS, NUMERIC_COLUMNS

_COMPETENCIA_PATTERNS = [
    re.compile(r"^(\d{4})-(\d{1,2})$"),
    re.compile(r"^(\d{4})/(\d{1,2})$"),
    re.compile(r"^(\d{4})(\d{2})$"),
]


@dataclass
class CleaningStats:
    rows_in: int
    exact_duplicates_removed: int
    rows_out: int


def normalize_competencia(value: object) -> str | None:
    """Normaliza a competência para AAAA-MM; retorna None se inválida."""
    text = str(value).strip() if value is not None else ""
    for pattern in _COMPETENCIA_PATTERNS:
        match = pattern.match(text)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            if 1 <= month <= 12 and 1990 <= year <= 2100:
                return f"{year:04d}-{month:02d}"
    return None


def parse_number(value: object) -> float | None:
    """Converte texto numérico (formato '1234.56' ou '1.234,56') em float."""
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "-", "nan", "NaN", "None", "null"}:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningStats]:
    df = raw.copy()
    df["competencia"] = df["competencia"].map(normalize_competencia)
    df["uf_sigla"] = df["uf_sigla"].astype(str).str.strip().str.upper()
    df["subgrupo_codigo"] = (
        df["subgrupo_codigo"].astype(str).str.strip().str.replace(r"\D", "", regex=True).str.zfill(4)
    )
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col].map(parse_number), errors="coerce").astype("float64")

    before = len(df)
    df = df.drop_duplicates(subset=KEY_COLUMNS + NUMERIC_COLUMNS, keep="first").reset_index(drop=True)
    stats = CleaningStats(rows_in=len(raw), exact_duplicates_removed=before - len(df), rows_out=len(df))
    return df, stats
