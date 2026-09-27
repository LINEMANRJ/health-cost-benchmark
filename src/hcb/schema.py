"""Contrato de dados (formato canônico) consumido pelo pipeline.

Granularidade: 1 linha = competência (mês) × UF de internação × subgrupo SIGTAP.
Nenhuma informação individual (paciente, profissional ou estabelecimento) faz parte do contrato.
"""
from __future__ import annotations

# Colunas do arquivo bruto no formato-contrato.
RAW_COLUMNS: dict[str, str] = {
    "competencia": "Mês de competência da produção aprovada (AAAA-MM)",
    "uf_sigla": "Sigla da UF de localização do estabelecimento de internação",
    "subgrupo_codigo": "Código do subgrupo de procedimento na Tabela SIGTAP (4 dígitos)",
    "qtd_internacoes": "Quantidade de AIH aprovadas (internações) no mês",
    "valor_total": "Valor total aprovado (R$, nominal) das AIH no mês",
    "dias_permanencia": "Soma dos dias de permanência das internações no mês",
}

KEY_COLUMNS = ["competencia", "uf_sigla", "subgrupo_codigo"]
NUMERIC_COLUMNS = ["qtd_internacoes", "valor_total", "dias_permanencia"]

# Colunas adicionadas na etapa de transformação.
DERIVED_COLUMNS: dict[str, str] = {
    "data": "Primeiro dia da competência (datetime)",
    "ano": "Ano da competência",
    "trimestre": "Trimestre da competência (AAAA-Qn)",
    "uf_nome": "Nome da UF",
    "regiao": "Grande região geográfica (IBGE)",
    "populacao": "População residente na UF (Censo 2022)",
    "subgrupo_nome": "Descrição do subgrupo SIGTAP",
    "grupo_codigo": "Código do grupo SIGTAP (2 dígitos)",
    "grupo_nome": "Descrição do grupo SIGTAP",
    "complexidade_referencia": "Complexidade predominante do subgrupo (referência)",
    "custo_por_internacao": "valor_total / qtd_internacoes (R$)",
    "custo_por_dia": "valor_total / dias_permanencia (R$)",
    "permanencia_media": "dias_permanencia / qtd_internacoes (dias)",
}

REGION_ORDER = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
