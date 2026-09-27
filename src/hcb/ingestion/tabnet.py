"""Adaptador para exportações CSV do TabNet/DATASUS (SIH/SUS).

O TabNet (http://tabnet.datasus.gov.br) exporta tabelas "Linha × Coluna" em CSV
separado por ';', codificação latin-1, com linhas de cabeçalho/rodapé descritivas
e números no formato brasileiro (1.234,56). Para montar o formato-contrato:

1. Em "Procedimentos hospitalares do SUS – por local de internação", escolha
   Linha = "Unidade da Federação", Coluna = "Ano/mês processamento" e, como
   filtro, um subgrupo de procedimento.
2. Exporte uma tabela por medida ("Quantidade aprovada", "Valor aprovado",
   "Dias de permanência") para cada subgrupo.
3. Use `parse_tabnet_csv` para converter cada arquivo em formato longo e
   `build_contract` para combinar as medidas no formato-contrato.

Observação: "Ano/mês processamento" difere de "Ano/mês atendimento"; documente
qual foi usado ao publicar resultados.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

MONTHS_PT = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
_UF_LABEL = re.compile(r"^\s*(\d{2})\s+(.+?)\s*$")
_PERIOD_LABEL = re.compile(r"^\s*(\d{4})/(\w{3})\s*$")


class TabnetParseError(ValueError):
    """Arquivo não reconhecido como exportação TabNet no layout esperado."""


def _to_number(value: str) -> float | None:
    value = str(value).strip()
    if value in {"", "-", "..."}:
        return None
    return float(value.replace(".", "").replace(",", "."))


def _to_competencia(label: str) -> str | None:
    match = _PERIOD_LABEL.match(label)
    if not match:
        return None
    year, month = match.groups()
    month_num = MONTHS_PT.get(month.lower()[:3])
    return f"{year}-{month_num:02d}" if month_num else None


def parse_tabnet_csv(content: str | bytes | Path, measure: str) -> pd.DataFrame:
    """Converte uma exportação TabNet (linha=UF, coluna=Ano/mês) em formato longo.

    Retorna colunas: uf_codigo_ibge, competencia, <measure>.
    """
    if isinstance(content, Path):
        content = content.read_bytes()
    if isinstance(content, bytes):
        content = content.decode("latin-1")

    lines = content.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.strip('"').startswith("Unidade da Federa")),
        None,
    )
    if header_idx is None:
        raise TabnetParseError("Cabeçalho 'Unidade da Federação' não encontrado.")

    body = []
    for line in lines[header_idx:]:
        if not line.strip() or line.strip('"').startswith("Total"):
            break
        body.append(line)

    table = pd.read_csv(io.StringIO("\n".join(body)), sep=";", dtype=str)
    first = table.columns[0]
    table = table.drop(columns=[c for c in table.columns if c.strip() == "Total"], errors="ignore")

    records = []
    for _, row in table.iterrows():
        uf_match = _UF_LABEL.match(str(row[first]))
        if not uf_match:
            continue
        for col in table.columns[1:]:
            competencia = _to_competencia(col)
            if competencia is None:
                raise TabnetParseError(f"Coluna de período não reconhecida: {col!r}")
            records.append(
                {
                    "uf_codigo_ibge": uf_match.group(1),
                    "competencia": competencia,
                    measure: _to_number(row[col]),
                }
            )
    if not records:
        raise TabnetParseError("Nenhuma linha de UF reconhecida no arquivo.")
    return pd.DataFrame(records)


def build_contract(
    quantity: pd.DataFrame,
    value: pd.DataFrame,
    days: pd.DataFrame,
    subgroup_code: str,
    ufs: pd.DataFrame,
) -> pd.DataFrame:
    """Combina as três medidas de um subgrupo no formato-contrato."""
    keys = ["uf_codigo_ibge", "competencia"]
    merged = quantity.merge(value, on=keys, how="outer").merge(days, on=keys, how="outer")
    uf_map = ufs.assign(uf_codigo_ibge=ufs["uf_codigo_ibge"].astype(str))[["uf_codigo_ibge", "uf_sigla"]]
    merged = merged.merge(uf_map, on="uf_codigo_ibge", how="left")
    merged["subgrupo_codigo"] = subgroup_code
    return merged[
        ["competencia", "uf_sigla", "subgrupo_codigo", "qtd_internacoes", "valor_total", "dias_permanencia"]
    ]
