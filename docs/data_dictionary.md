# Dicionário de dados

## 1. Formato-contrato (dados brutos): `data/raw/*.csv`

Granularidade: **1 linha = competência × UF × subgrupo SIGTAP**. Chave única: `competencia + uf_sigla +
subgrupo_codigo`.

| Coluna | Tipo | Obrigatória | Descrição | Regras de validação |
|---|---|---|---|---|
| `competencia` | texto `AAAA-MM` | sim | Mês de competência da produção aprovada | Aceita `AAAA-MM`, `AAAA/MM` e `AAAAMM`; mês entre 1 e 12 |
| `uf_sigla` | texto (2) | sim | UF do estabelecimento de internação | Deve existir em `data/reference/ufs.csv` (espaços e minúsculas são corrigidos) |
| `subgrupo_codigo` | texto (4) | sim | Subgrupo de procedimento na Tabela SIGTAP | Deve existir em `data/reference/subgrupos_sigtap.csv` (zero à esquerda é restaurado) |
| `qtd_internacoes` | inteiro | sim | Quantidade de AIH aprovadas | Numérico, inteiro e > 0 |
| `valor_total` | decimal (R$) | sim | Valor total aprovado, em R$ nominais | Numérico e ≥ 0; aceita `1234.56` e `1.234,56` |
| `dias_permanencia` | inteiro | não* | Soma dos dias de permanência | ≥ 0. Se ausente, gera alerta e o custo por dia fica nulo |

\* Necessário apenas para `custo_por_dia` e `permanencia_media`.

## 2. Tabela fato (processada): `data/processed/fato_internacoes.csv`

| Coluna | Tipo | Descrição / fórmula |
|---|---|---|
| `competencia` | texto | Igual ao bruto, normalizada |
| `data` | data | Primeiro dia da competência |
| `ano` | inteiro | Ano da competência |
| `trimestre` | texto | `AAAAQn` |
| `uf_sigla`, `uf_nome` | texto | UF |
| `regiao` | categoria | Grande região IBGE (Norte, Nordeste, Centro-Oeste, Sudeste, Sul) |
| `populacao` | inteiro | População residente da UF no Censo 2022 (denominador da taxa de utilização) |
| `grupo_codigo`, `grupo_nome` | texto | Grupo SIGTAP (03 clínicos, 04 cirúrgicos, 05 transplantes) |
| `subgrupo_codigo`, `subgrupo_nome` | texto | Subgrupo SIGTAP |
| `complexidade_referencia` | texto | Complexidade predominante do subgrupo (Média/Alta). É uma referência simplificada do projeto |
| `qtd_internacoes` | inteiro | Quantidade de AIH aprovadas |
| `valor_total` | decimal | Valor aprovado (R$) |
| `dias_permanencia` | decimal | Dias de permanência |
| `custo_por_internacao` | decimal | `valor_total ÷ qtd_internacoes` |
| `custo_por_dia` | decimal | `valor_total ÷ dias_permanencia` (nulo se dias ≤ 0) |
| `permanencia_media` | decimal | `dias_permanencia ÷ qtd_internacoes` |

### Colunas adicionais em `fato_internacoes_com_atipicidade.csv`

| Coluna | Descrição |
|---|---|
| `log_custo` | ln(custo por internação) |
| `residuo_log` | Desvio em log em relação ao esperado (ver metodologia) |
| `custo_esperado` | Custo por internação esperado para a célula (R$) |
| `z_robusto` | Escore padronizado pela variância a/n + b e reescalado pela MAD |
| `atipico` | `abs(z_robusto) > limiar` (padrão 3,5) e ≥ 5 internações |
| `direcao_atipicidade` | "acima do esperado" / "abaixo do esperado" |
| `atipico_iqr` | Método de referência: fora de 1,5 × IQR do log-custo no subgrupo |
| `excesso_estimado` | Para atípicos acima do esperado: `valor_total − custo_esperado × qtd` (R$) |

## 3. Quarentena: `data/processed/quarentena.csv`

Colunas do formato-contrato após o tratamento, mais `motivo` (nomes das regras violadas separados por `;`).

## 4. Tabelas de referência: `data/reference/`

| Arquivo | Colunas | Fonte |
|---|---|---|
| `ufs.csv` | `uf_codigo_ibge`, `uf_sigla`, `uf_nome`, `regiao`, `populacao_censo_2022` | IBGE (códigos de UF e Censo 2022) |
| `subgrupos_sigtap.csv` | `subgrupo_codigo`, `subgrupo_nome`, `grupo_codigo`, `grupo_nome`, `complexidade_referencia` | SIGTAP/DATASUS (subconjunto de 16 subgrupos de internação) |

## 5. Saídas de indicadores: `data/processed/indicadores/`

| Arquivo | Conteúdo |
|---|---|
| `kpis.json` | KPIs do conjunto completo |
| `serie_mensal.csv`, `serie_mensal_regiao.csv` | Valor, internações, custo médio, média móvel de 3 meses e variação em 12 meses |
| `por_regiao.csv`, `por_uf.csv` | Agregados, percentis, taxa por 10 mil habitantes e índice ajustado ao mix |
| `por_subgrupo.csv` | Agregados por subgrupo |
| `concentracao_subgrupos.csv` | Participação, participação acumulada e núcleo de Pareto |
| `tendencia_por_subgrupo.csv`, `tendencia_por_regiao.csv` | Theil–Sen anualizado, IC 95%, Mann–Kendall e p ajustado |
| `variacao_entre_ufs.csv` | CV, razão P90/P10 e UFs extremas por subgrupo |
| `diferencas_regionais.csv` | Kruskal–Wallis, ε² e p (Holm) por subgrupo |
| `associacao_volume_custo.csv` | Spearman volume × custo por subgrupo |
| `atipicos.csv` | Células atípicas ordenadas por abs(z) |
