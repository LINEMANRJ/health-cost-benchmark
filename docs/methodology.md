# Metodologia

Unidade de análise: **célula = competência × UF × subgrupo SIGTAP**. Notação: para uma célula *i*,
`V_i` = valor aprovado, `N_i` = internações, `D_i` = dias de permanência.

## 1. Indicadores

| Indicador | Fórmula | Por que assim |
|---|---|---|
| **Valor total** | Σ V_i | Volume financeiro |
| **Internações** | Σ N_i | Volume assistencial |
| **Custo médio por internação** | Σ V_i ÷ Σ N_i | Média **ponderada**. A média simples das células (média de médias) daria o mesmo peso a uma UF com 30 internações e a outra com 60 mil |
| **Mediana (células)** | mediana de V_i/N_i | Tendência central robusta entre UFs e meses. Uma célula = um voto |
| **Mediana ponderada** | quantil 50% de V_i/N_i ponderado por N_i | Custo da célula onde está a "internação mediana". É menos sensível a subgrupos de altíssimo custo do que a média |
| **Custo por dia** | Σ V_i ÷ Σ D_i | Separa custo de "diária" de custo por tempo de permanência |
| **Permanência média** | Σ D_i ÷ Σ N_i | Componente de uso de leito |
| **Variação 12 meses** | CM(últimos 12m) ÷ CM(12m anteriores) − 1 | Compara janelas completas e neutraliza a sazonalidade. Exige ≥ 24 meses |
| **Variação mensal a/a** | CM(mês) ÷ CM(mesmo mês do ano anterior) − 1 | Mostra aceleração ou desaceleração sem efeito sazonal |
| **Média móvel 3 meses** | média de CM em t, t−1, t−2 | Suaviza ruído para leitura visual |
| **Taxa de utilização** | Σ N ÷ (população × meses) × 10.000 | Internações por 10 mil habitantes por mês. Usa a UF de *internação* e, portanto, inclui pacientes de outras UFs |
| **Índice de custo ajustado ao mix (ICAM)** | Σ V_i ÷ Σ (N_i × CM_nacional[subgrupo, mês]) | **Padronização indireta**. Responde: "quanto esta UF gasta em relação ao que gastaria pagando o custo médio nacional por cada tipo de procedimento que fez?". 1,10 = 10% acima do esperado para o seu mix e período |
| **Participação e Pareto** | V_k ÷ ΣV; acumulado em ordem decrescente | O núcleo de Pareto é o menor conjunto de itens que soma 80% do valor |
| **HHI** | Σ (participação_k)² × 10.000 | Concentração: < 1.500 baixa, 1.500–2.500 moderada, > 2.500 alta (faixas usuais em análise de concentração) |

## 2. Análises estatísticas

### 2.1 Tendência temporal
- Série: custo médio mensal (ponderado) do recorte.
- **Theil–Sen** sobre `ln(CM_t) ~ t`: é a mediana das inclinações entre todos os pares de meses, robusta a
  meses atípicos. Crescimento anual = `exp(12 × inclinação) − 1`, com IC 95% do próprio estimador.
- **Mann–Kendall** (τ de Kendall contra o tempo) para testar tendência monotônica.
- **Correção de Holm** quando várias séries (regiões ou subgrupos) são testadas.
- *Limitação:* o teste não corrige autocorrelação serial, que tende a tornar os p-valores otimistas. Por isso,
  prefira ler o tamanho do efeito (crescimento anual e IC).

### 2.2 Variação entre categorias
- Para cada subgrupo, calcula-se o custo médio de cada UF no período inteiro, considerando apenas UFs com
  **≥ 30 internações** para evitar instabilidade de pequenos números.
- **CV entre UFs** = desvio-padrão ÷ média e **razão P90/P10**. Comparar a dispersão *dentro do mesmo
  subgrupo* evita confundir heterogeneidade com mix de procedimentos.

### 2.3 Diferenças entre regiões
- **Kruskal–Wallis** (não paramétrico, sem pressupor normalidade) por subgrupo, com as UFs agrupadas por
  região.
- **Unidade = UF no período**, e não UF × mês. Meses da mesma UF são correlacionados, e tratá-los como
  independentes (pseudo-replicação) inflaria o n e a significância.
- **Tamanho de efeito ε² = H ÷ (n − 1)**: < 0,01 desprezível · < 0,08 pequeno · < 0,26 moderado · ≥ 0,26
  grande.
- p-valores ajustados por **Holm** entre os 16 subgrupos.
- *Limitação:* com n ≤ 27 UFs, o poder é baixo para efeitos pequenos. Ausência de significância não é
  evidência de igualdade.

### 2.4 Associação volume × custo
- **Spearman** entre internações e custo médio das UFs, por subgrupo.
- É uma associação descritiva. Não demonstra economia de escala nem efeito causal.

## 3. Detecção de atípicos

**Objetivo:** priorizar células para verificação (auditoria de faturamento, erro de registro, mudança de
perfil). Atipicidade **não** prova erro, fraude ou ineficiência.

### Método principal: escore robusto contextual (funnel plot com sobredispersão)

1. **Valor esperado da célula** (escala log), usando medianas, que são robustas a atípicos:

   `esperado_i = mediana(log custo | subgrupo, UF) + [mediana(log custo | subgrupo, mês) − mediana(log custo | subgrupo)]`

   Ou seja, é o nível típico daquela UF para aquele subgrupo, deslocado pelo movimento nacional do mês
   (reajustes, sazonalidade).

2. **Resíduo:** `r_i = log(custo_i) − esperado_i`.

3. **Variância esperada do resíduo:** `Var(r_i) ≈ a / N_i + b`
   - `a / N_i` é o ruído amostral: a média de N internações varia menos quando N é grande.
   - `b` é a sobredispersão: variação real entre células além do acaso.
   - `a` e `b` são estimados por mínimos quadrados em `r²` para cada subgrupo, excluindo iterativamente as
     células com abs(z) > 4 para que os próprios atípicos não inflem a variância.

4. **Escore:** `z_i = r_i ÷ √(a/N_i + b)`, recentrado e reescalado pela MAD.

5. **Regra:** atípico se abs(z) > **3,5** (Iglewicz & Hoaglin, 1993) e N ≥ **5** internações. Os dois valores
   são configuráveis em `settings.yaml`.

Sem o termo `a/N`, células pequenas seriam sinalizadas o tempo todo por ruído e as grandes nunca seriam. É o
problema clássico que os funnel plots resolvem (Spiegelhalter, 2005).

### Validação na base sintética (com gabarito)

| Limiar abs(z) | Sinalizadas | Precisão | Recall |
|---:|---:|---:|---:|
| 3,0 | 97 | 41% | 100% |
| **3,5 (padrão)** | **55** | **73%** | **100%** |
| 4,0 | 44 | 91% | 100% |
| 5,0 | 40 | 100% | 100% |

Anomalias injetadas: 40 células com custo multiplicado por 2,5–5×. Os "falsos positivos" são flutuações
extremas do próprio processo gerador. A validação completa está em `notebooks/03_deteccao_atipicos.ipynb`, e
o teste `tests/test_statistics_outliers.py` exige recall ≥ 90% e precisão ≥ 50%.

### Método de referência
**Cercas de Tukey** (1,5 × IQR) sobre o log-custo dentro do subgrupo, exibidas no box plot. São simples e
conhecidas, mas não consideram UF, mês nem tamanho da célula.

### Excesso estimado
Para atípicos acima do esperado: `V_i − custo_esperado_i × N_i`. É uma **ordem de grandeza** para priorizar a
investigação, não um valor a recuperar.

## 4. Limites de interpretação

- **Correlação não implica causalidade.** Diferenças entre regiões, UFs ou volumes são associações e podem
  refletir gravidade dos casos dentro do subgrupo, estrutura de rede, referência de pacientes, incentivos,
  tabelas complementares ou qualidade de registro.
- O ICAM ajusta o **mix de subgrupos**, mas não a gravidade, a idade nem as comorbidades dentro do subgrupo.
- Valores são **nominais**. Crescimento de custo inclui inflação e reajustes de tabela.
- "Custo" aqui significa **valor aprovado pelo SUS**, e não custo econômico hospitalar.

## Referências

- Iglewicz, B.; Hoaglin, D. (1993). *How to Detect and Handle Outliers*. ASQC Quality Press.
- Spiegelhalter, D. (2005). Funnel plots for comparing institutional performance. *Statistics in Medicine*,
  24(8), 1185–1202.
- Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *JASA*, 63(324).
- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scand. J. Statistics*, 6(2).
- Tomczak, M.; Tomczak, E. (2014). The need to report effect size estimates revisited (ε² para
  Kruskal–Wallis). *Trends in Sport Sciences*, 1(21).
