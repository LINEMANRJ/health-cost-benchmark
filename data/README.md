# Dados

| Pasta | Conteúdo | Versionado? |
|---|---|---|
| `reference/` | Tabelas de referência: UFs (IBGE, Censo 2022) e subgrupos SIGTAP | ✅ |
| `sample/` | Pequenas amostras da base **sintética** (bruta e processada) para inspeção rápida | ✅ |
| `raw/` | Dados brutos no formato-contrato. A base sintética é gerada aqui na 1ª execução, junto com o gabarito de anomalias | ❌ (reprodutível) |
| `external/` | Exportações manuais do TabNet/DATASUS, se usadas | ❌ |
| `processed/` | Tabela fato, quarentena e indicadores gerados pelo pipeline | ❌ (reprodutível) |

> ⚠️ Os dados deste repositório são **sintéticos**. Fonte, licença, período, granularidade e limitações:
> [`docs/data_sources.md`](../docs/data_sources.md). Dicionário: [`docs/data_dictionary.md`](../docs/data_dictionary.md).

Nenhum arquivo contém dados pessoais. O contrato é agregado por competência × UF × subgrupo.
