# Relatório de qualidade dos dados

- **Gerado em:** 2026-09-27T02:03:58+00:00
- **Status:** APROVADO COM ALERTAS
- **Linhas recebidas (após remoção de duplicatas exatas):** 15.012
- **Linhas aprovadas:** 14.992
- **Linhas em quarentena:** 20 (0,133%)

## Regras por linha

| Regra | Descrição | Severidade | Linhas com falha |
|---|---|---|---:|
| `competencia_valida` | Competência presente e no formato AAAA-MM | erro | 0 |
| `uf_valida` | UF pertence à tabela de referência do IBGE | erro | 3 |
| `subgrupo_valido` | Subgrupo pertence à tabela de referência SIGTAP do projeto | erro | 0 |
| `qtd_preenchida` | Quantidade de internações numérica e preenchida | erro | 0 |
| `qtd_positiva` | Quantidade de internações > 0 (valor sem internação é inconsistente) | erro | 4 |
| `qtd_inteira` | Quantidade de internações é número inteiro | erro | 0 |
| `valor_preenchido` | Valor total numérico e preenchido | erro | 8 |
| `valor_nao_negativo` | Valor total não negativo | erro | 5 |
| `chave_unica` | Uma única linha por competência × UF × subgrupo (sem conflito) | erro | 0 |
| `dias_nao_negativo` | Dias de permanência não negativos | erro | 0 |
| `dias_preenchido` | Dias de permanência preenchidos (necessário p/ custo por dia) | alerta | 0 |
| `permanencia_plausivel` | Permanência média entre 0,5 e 60 dias | alerta | 0 |
| `custo_unitario_plausivel` | Custo por internação entre R$ 50 e R$ 500 mil | alerta | 0 |

## Verificações do conjunto

| Verificação | Severidade | Resultado | Detalhe |
|---|---|---|---|
| `proporcao_rejeitada` | erro | ok | 0,133% das linhas rejeitadas |
| `periodo_minimo` | erro | ok | 36 meses (2022-01 a 2024-12) |
| `meses_sem_lacuna` | alerta | ok | sem lacunas |
| `cobertura_ufs` | alerta | ok | todas presentes |
