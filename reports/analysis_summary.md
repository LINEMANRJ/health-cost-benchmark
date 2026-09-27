# Resumo analítico — Health Cost Benchmark

> ⚠️ **Resultados gerados sobre base SINTÉTICA.** Os números ilustram o funcionamento do
> pipeline e dos métodos; não descrevem a realidade do SUS.

## Visão geral

- Período: **2022-01 a 2024-12** (36 meses)
- Valor total aprovado: **R$ 65,9 bi**
- Internações: **35.535.036**
- Custo médio por internação: **R$ 1.854,73** (mediana ponderada R$ 1.246,10)
- Custo por dia de permanência: **R$ 451,69**; permanência média 4,1 dias
- Variação do custo médio (últimos 12 meses vs. 12 anteriores): **+6,1%**
- Qualidade dos dados: **APROVADO COM ALERTAS** — 20 linhas em quarentena (0,13%)

## 1. Como os custos evoluem ao longo do tempo?

| Região | Crescimento anual (Theil–Sen) | IC 95% | p ajustado | Leitura |
|---|---:|---|---:|---|
| Nordeste | +6,4% | 5,9% a 6,7% | 3.06e-14 | alta |
| Norte | +6,3% | 5,9% a 6,7% | 2.66e-14 | alta |
| Sul | +6,3% | 6,0% a 6,5% | 1.12e-14 | alta |
| Centro-Oeste | +6,2% | 5,9% a 6,6% | 3.06e-14 | alta |
| Sudeste | +6,1% | 5,8% a 6,4% | 2.06e-09 | alta |

Subgrupos com maior crescimento anual do custo médio: Cirurgia do aparelho da visão (+6,4%); Tratamentos clínicos (outras especialidades) (+6,2%); Cirurgia em oncologia (+6,2%).

## 2. Quais categorias apresentam maior variação?

Coeficiente de variação (CV) do custo médio por internação entre UFs, por subgrupo:

| Subgrupo | UFs | CV entre UFs | Razão P90/P10 | Menor custo | Maior custo |
|---|---:|---:|---:|---|---|
| Cirurgia do aparelho circulatório | 27 | 12,1% | 1,38 | CE (R$ 7.467) | SP (R$ 11.252) |
| Tratamento de lesões, envenenamentos e outros, decorrentes de causas externas | 27 | 11,9% | 1,35 | BA (R$ 815) | DF (R$ 1.200) |
| Cirurgia do sistema osteomuscular | 27 | 11,6% | 1,34 | RN (R$ 2.015) | PR (R$ 2.814) |
| Tratamento em oncologia | 27 | 11,3% | 1,30 | MA (R$ 2.079) | ES (R$ 3.150) |
| Cirurgia em oncologia | 27 | 10,7% | 1,34 | PI (R$ 3.319) | AC (R$ 4.830) |

## 3. Existem valores atípicos?

Foram sinalizadas **55 células** (competência × UF × subgrupo) com |z robusto| acima do limiar.
48 estão acima do esperado, somando excesso estimado de **R$ 857,2 mi** em relação ao custo esperado.

| Competência | UF | Subgrupo | Internações | Custo/internação | Esperado | z |
|---|---|---|---:|---:|---:|---:|
| 2024-03 | SC | Tratamentos clínicos (outras especialidades) | 13.493 | R$ 5.831 | R$ 1.306 | 89.9 |
| 2024-05 | ES | Cirurgia do aparelho digestivo, órgãos anexos e parede abdominal | 2.246 | R$ 5.689 | R$ 1.450 | 81.5 |
| 2022-10 | AL | Parto e nascimento | 2.056 | R$ 2.617 | R$ 684 | 75.8 |
| 2024-06 | SE | Cirurgia do sistema osteomuscular | 920 | R$ 10.772 | R$ 2.095 | 75.6 |
| 2024-07 | DF | Cirurgia do sistema osteomuscular | 1.292 | R$ 11.965 | R$ 2.626 | 74.5 |
| 2024-09 | PA | Cirurgia do aparelho geniturinário | 1.742 | R$ 4.794 | R$ 1.173 | 71.5 |
| 2024-06 | RS | Cirurgia do aparelho circulatório | 2.008 | R$ 48.752 | R$ 9.601 | 69.8 |
| 2022-11 | SP | Tratamentos clínicos (outras especialidades) | 68.351 | R$ 3.836 | R$ 1.268 | 67.3 |

Atipicidade indica prioridade de auditoria/investigação, não erro ou irregularidade comprovada.

## 4. Existem diferenças relevantes entre regiões?

| Região | Custo médio/internação | Índice ajustado ao mix | Internações/10 mil hab./mês | Participação no valor |
|---|---:|---:|---:|---:|
| Sudeste | R$ 1.999,24 | 1,067 | 48,8 | 45,2% |
| Sul | R$ 1.995,76 | 1,065 | 56,2 | 18,3% |
| Centro-Oeste | R$ 1.759,38 | 0,956 | 48,8 | 7,6% |
| Norte | R$ 1.625,73 | 0,910 | 41,4 | 6,4% |
| Nordeste | R$ 1.619,52 | 0,882 | 46,3 | 22,4% |

Kruskal–Wallis por subgrupo (UFs agrupadas por região): diferença significativa após Holm em **4 de 16** subgrupos.
Maiores efeitos: Tratamentos clínicos (outras especialidades) (ε² = 0,72, grande; maior mediana: Sul); Outras cirurgias (ε² = 0,69, grande; maior mediana: Sul); Tratamento em oncologia (ε² = 0,67, grande; maior mediana: Sul).

Diferenças observadas são associações: podem refletir mix de casos dentro do subgrupo, complexidade da rede, incentivos/tabelas complementares ou registro, e não indicam por si só ineficiência.

## 5. Quais grupos concentram maior volume financeiro?

8 de 16 subgrupos concentram 80% do valor total (HHI = 1.133).

| Subgrupo | Valor total | Participação | Internações | Custo médio |
|---|---:|---:|---:|---:|
| Tratamentos clínicos (outras especialidades) | R$ 14,1 bi | 21,5% | 11.343.444 | R$ 1.246,51 |
| Cirurgia do aparelho circulatório | R$ 10,5 bi | 15,9% | 1.107.616 | R$ 9.477,88 |
| Cirurgia do sistema osteomuscular | R$ 8,1 bi | 12,3% | 3.314.505 | R$ 2.441,55 |
| Cirurgia do aparelho digestivo, órgãos anexos e parede abdominal | R$ 5,9 bi | 9,0% | 4.048.773 | R$ 1.467,87 |
| Parto e nascimento | R$ 3,9 bi | 6,0% | 4.795.181 | R$ 819,19 |
| Tratamento em oncologia | R$ 3,7 bi | 5,7% | 1.461.844 | R$ 2.553,36 |

UFs com maior valor total: SP (24,3%), MG (10,9%), RJ (8,1%).
