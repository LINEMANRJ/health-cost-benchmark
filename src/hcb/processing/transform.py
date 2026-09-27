"""Etapa de transformação: enriquecimento com referências e métricas derivadas."""
from __future__ import annotations

import numpy as np
import pandas as pd

from hcb.schema import REGION_ORDER


class TransformError(RuntimeError):
    """Falha de integridade ao enriquecer os dados."""


def transform(df: pd.DataFrame, ufs: pd.DataFrame, subgroups: pd.DataFrame) -> pd.DataFrame:
    """Gera a tabela fato analítica (1 linha = competência × UF × subgrupo)."""
    uf_cols = ufs[["uf_sigla", "uf_nome", "regiao", "populacao_censo_2022"]].rename(
        columns={"populacao_censo_2022": "populacao"}
    )
    fact = df.merge(uf_cols, on="uf_sigla", how="left", validate="many_to_one")
    fact = fact.merge(subgroups, on="subgrupo_codigo", how="left", validate="many_to_one")
    if fact[["regiao", "subgrupo_nome"]].isna().any().any():
        raise TransformError("Registros sem correspondência nas tabelas de referência após validação.")

    fact["data"] = pd.PeriodIndex(fact["competencia"], freq="M").to_timestamp()
    fact["ano"] = fact["data"].dt.year
    fact["trimestre"] = fact["data"].dt.to_period("Q").astype(str)
    fact["qtd_internacoes"] = fact["qtd_internacoes"].astype("int64")
    fact["custo_por_internacao"] = fact["valor_total"] / fact["qtd_internacoes"]
    days = fact["dias_permanencia"].where(fact["dias_permanencia"] > 0)
    fact["custo_por_dia"] = fact["valor_total"] / days
    fact["permanencia_media"] = days / fact["qtd_internacoes"]
    fact["regiao"] = pd.Categorical(fact["regiao"], categories=REGION_ORDER, ordered=True)

    ordered = [
        "competencia", "data", "ano", "trimestre",
        "uf_sigla", "uf_nome", "regiao", "populacao",
        "grupo_codigo", "grupo_nome", "subgrupo_codigo", "subgrupo_nome", "complexidade_referencia",
        "qtd_internacoes", "valor_total", "dias_permanencia",
        "custo_por_internacao", "custo_por_dia", "permanencia_media",
    ]
    fact = fact[ordered].sort_values(["competencia", "uf_sigla", "subgrupo_codigo"]).reset_index(drop=True)
    fact = fact.replace([np.inf, -np.inf], np.nan)
    return fact
