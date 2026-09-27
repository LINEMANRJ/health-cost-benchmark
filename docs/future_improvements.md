# Future improvements

O projeto foi estruturado para evoluir sem reescrever o núcleo. Cada frente abaixo tem um **ponto de
extensão já preparado** no código.

## 1. Previsão de custos

**Já existe:** `hcb/forecasting.py` com um baseline sazonal com deriva e a função `backtest()` para medir o
MAPE fora da amostra.

**Próximos passos:**
- Modelos candidatos: ETS/Holt-Winters, SARIMA e gradient boosting com lags e calendário, por subgrupo e
  região (modelos hierárquicos com reconciliação *bottom-up*/MinT).
- Critério de adoção: **superar o baseline** no backtest com janela deslizante (*rolling origin*), com
  intervalos de previsão calibrados.
- Deflacionar a série (IPCA ou índice setorial) para separar volume, preço e mix.
- Uso: projeção orçamentária e alertas quando o realizado sai do intervalo previsto.

## 2. Detecção de anomalias com Machine Learning

**Já existe:** um escore robusto com gabarito sintético (precisão e recall mensuráveis) e a coluna
`z_robusto`, que serve de *feature* e de linha de base.

**Próximos passos:**
- Isolation Forest ou Local Outlier Factor sobre *features* multivariadas: resíduo de custo, permanência
  média, variação a/a, participação no mix da UF e volume relativo.
- Detecção em série temporal (STL + resíduos, change-point detection) para mudanças de patamar, e não só
  para picos isolados.
- Avaliação com o gabarito sintético (precision@k) e rotulagem ativa pelos auditores (*human-in-the-loop*).
- Explicabilidade por célula (SHAP ou contribuição por *feature*) para justificar cada alerta.

## 3. Análise conversacional

**Já existe:** `hcb/ai/tools.py` com funções determinísticas (`get_kpis`, `compare_by`, `cost_trend`,
`list_outliers`), especificações JSON Schema (`TOOL_SPECS`) e um despachante (`call_tool`) com validação de
entrada.

**Próximos passos:**
- Aba "Pergunte aos dados" no Streamlit (`st.chat_input`). O LLM interpreta a pergunta, chama as ferramentas e
  redige a resposta **citando os números retornados**.
- **Regra de ouro:** o modelo nunca calcula nem inventa números. Todo valor vem de uma ferramenta testada.
- Credenciais via variável de ambiente ou `st.secrets` (já ignorado no `.gitignore`), **nunca no código**.

## 4. Agente de IA para exploração dos dados

**Próximos passos:**
- Agente com *tool use* que encadeia análises. Por exemplo: "encontre os subgrupos com maior crescimento, veja
  quais UFs puxam o aumento e liste os atípicos relacionados".
- Novas ferramentas: decomposição da variação (volume × preço × mix), comparação entre períodos e geração de
  relatório.
- Guardrails: ferramentas somente leitura, limite de passos, lista de filtros permitidos (já validada em
  `_filter`) e registro das chamadas para auditoria.
- Avaliação: conjunto de perguntas com respostas de referência calculadas pelo pipeline (eval automatizado).

## 5. Engenharia de dados

- Ingestão automatizada do TabNet ou FTP (PySUS) com cache e agendamento. Microdados só com agregação
  imediata e descarte das colunas pessoais.
- Armazenamento em Parquet ou DuckDB e orquestração (Prefect/Airflow) com lineage.
- Contratos de dados formais (Pandera ou Great Expectations) no lugar das regras próprias.
- Deploy do dashboard (Streamlit Community Cloud ou container) com dados reais agregados.

## 6. Analítica

- Decomposição da variação do gasto em efeitos **volume**, **preço** e **mix** (índices de Laspeyres/Paasche).
- Ajuste por perfil de casos com microdados agregados por faixa etária e sexo (padronização direta).
- Análise por município de residência (fluxo de pacientes entre UFs).
