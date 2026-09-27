# Fontes de dados

## 1. Fonte de referência: SIH/SUS (DATASUS)

| Item | Descrição |
|---|---|
| **Fonte** | Sistema de Informações Hospitalares do SUS (SIH/SUS), Ministério da Saúde, disseminado pelo DATASUS |
| **Conteúdo** | Autorizações de Internação Hospitalar (AIH) aprovadas: quantidade, valor aprovado e dias de permanência |
| **Acesso agregado** | TabNet: *DATASUS → Informações de Saúde (TabNet) → Assistência à Saúde → Produção Hospitalar (SIH/SUS) → Dados consolidados AIH (RD), por local de internação* (http://tabnet.datasus.gov.br) |
| **Acesso a microdados** | Arquivos `RD{UF}{AA}{MM}.dbc` no FTP do DATASUS (`ftp.datasus.gov.br/dissemin/publicos/SIHSUS/`). Podem ser lidos com a biblioteca PySUS. **Não usados neste projeto** (ver "Por que dados agregados") |
| **Tabela de procedimentos** | SIGTAP, a tabela de procedimentos, medicamentos e OPM do SUS (http://sigtap.datasus.gov.br), com hierarquia grupo → subgrupo → forma de organização → procedimento |
| **Período disponível** | Série mensal desde 2008 no layout atual (tabelas SIGTAP). Os meses mais recentes sofrem atualizações retroativas |
| **Granularidade adotada** | Competência (mês) × UF do estabelecimento de internação × subgrupo SIGTAP |
| **Referências auxiliares** | IBGE: códigos e nomes das UFs, grandes regiões e população do Censo Demográfico 2022 (`data/reference/ufs.csv`) |

### Regras de uso e licença

- Os dados do DATASUS são **públicos e de acesso livre**, divulgados nos termos da Lei de Acesso à Informação
  (Lei nº 12.527/2011) e da Política de Dados Abertos do Poder Executivo federal (Decreto nº 8.777/2016).
- **Cite a fonte** ao publicar resultados, por exemplo: "Ministério da Saúde – Sistema de Informações
  Hospitalares do SUS (SIH/SUS), via DATASUS/TabNet, acesso em AAAA-MM-DD". Informe também se foi usado
  "ano/mês de processamento" ou "ano/mês de atendimento".
- **LGPD (Lei nº 13.709/2018):** o projeto usa apenas dados **agregados por UF**, sem dados pessoais.
  Microdados de AIH, mesmo sem nome, contêm atributos como idade, sexo, município e diagnóstico, que exigem
  cuidados de minimização e de risco de reidentificação.
- Confira os termos vigentes no portal do DATASUS e em dados.gov.br antes de redistribuir extrações. **Este
  repositório não redistribui dados reais.**

### Por que dados agregados

1. **Privacidade.** Sem dados pessoais, não há base legal a justificar nem risco de reidentificação.
2. **Adequação à pergunta.** Benchmarking de custo por UF e categoria não precisa de registro individual.
3. **Portabilidade.** Tabelas do TabNet são pequenas, reprodutíveis e documentadas.

## 2. Base SINTÉTICA (padrão do repositório)

> ⚠️ **Os números exibidos neste repositório (README, dashboard, notebooks e relatórios) vêm de uma base
> sintética.** Ela imita a estrutura e as ordens de grandeza do SIH/SUS agregado, mas **não é dado real** e
> não deve ser usada para conclusões sobre o SUS.

**Por que existe:** o acesso automatizado ao TabNet/FTP do DATASUS é instável e pode ser bloqueado em
ambientes de CI ou redes corporativas. A base sintética permite executar o projeto de ponta a ponta, offline
e de forma determinística.

| Item | Valor |
|---|---|
| Arquivo | `data/raw/sih_sus_sintetico.csv` (gerado na 1ª execução; não versionado) |
| Gerador | `src/hcb/ingestion/synthetic.py` · semente 42 · `config/settings.yaml` |
| Período | 2022-01 a 2024-12 (36 meses) |
| Granularidade | Competência × UF (27) × subgrupo SIGTAP (16) |
| Linhas | cerca de 15 mil |
| Gabarito | `data/raw/sih_sus_sintetico_gabarito.csv`: lista de todas as anomalias e problemas injetados |
| Amostras versionadas | `data/sample/amostra_bruta_sintetica.csv`, `data/sample/amostra_fato_internacoes.csv` |

**Mecanismos simulados:**

| Mecanismo | Parâmetro |
|---|---|
| Volume mensal | ~0,49% da população da UF/mês (Censo 2022), com fator regional de utilização (Norte 0,85 … Sul 1,15) |
| Mix de procedimentos | Participação fixa por subgrupo; transplantes concentrados em 12 UFs com centros de referência |
| Custo de referência | Por subgrupo, de ~R$ 700 (parto) a ~R$ 32 mil (transplante) |
| Diferença regional de custo | Fatores Nordeste 0,92 · Norte 0,95 · Centro-Oeste 1,02 · Sudeste 1,08 · Sul 1,10 |
| Heterogeneidade UF × subgrupo | Fator log-normal (σ = 0,07), estável no tempo |
| Reajuste nominal | +0,5% ao mês (~6,2% ao ano) |
| Sazonalidade | −7% de volume em dez/jan; +10% em mai–jul para tratamentos clínicos |
| Ruído amostral | Custo médio da célula com CV de 60% ÷ √n, como na média de n internações |
| **Anomalias injetadas** | 40 células com valor multiplicado por 2,5–5× (apenas células com ≥ 20 internações) |
| **Problemas de qualidade** | 15 duplicatas, 8 valores nulos, 5 negativos, 4 com quantidade zero, 3 UFs inválidas e 30 siglas com espaço ou minúscula |

Como os problemas são conhecidos, a base serve também como **teste de aceitação** do pipeline. Os testes
verificam que 100% dos problemas de qualidade são capturados e que a detecção de atípicos recupera ≥ 90% das
anomalias.

## 3. Como usar dados reais (TabNet)

1. No TabNet, escolha a tabela de procedimentos hospitalares do SUS **por local de internação**, com
   *Linha = Unidade da Federação*, *Coluna = Ano/mês processamento* e o **subgrupo de procedimento** como
   filtro em *Seleções disponíveis*.
2. Exporte em CSV as medidas **Quantidade aprovada**, **Valor aprovado** e **Dias de permanência**, uma
   tabela por medida e por subgrupo.
3. Converta as tabelas para o formato-contrato:

   ```python
   from pathlib import Path
   import pandas as pd
   from hcb.ingestion.tabnet import parse_tabnet_csv, build_contract

   ufs = pd.read_csv("data/reference/ufs.csv", dtype=str)
   parts = []
   for code in ["0303", "0310", "0407"]:  # subgrupos exportados
       q = parse_tabnet_csv(Path(f"data/external/qtd_{code}.csv"), "qtd_internacoes")
       v = parse_tabnet_csv(Path(f"data/external/valor_{code}.csv"), "valor_total")
       d = parse_tabnet_csv(Path(f"data/external/dias_{code}.csv"), "dias_permanencia")
       parts.append(build_contract(q, v, d, code, ufs))
   pd.concat(parts).to_csv("data/raw/sih_sus_tabnet.csv", index=False)
   ```

4. Em `config/settings.yaml`, defina `source.type: contract_csv` e `source.raw_file:
   data/raw/sih_sus_tabnet.csv`. Depois rode `python -m hcb.pipeline`.

As mesmas regras de validação se aplicam. Por exemplo, meses com "-" no TabNet viram nulos e vão para a
quarentena.

## 4. Limitações da fonte real (para interpretação)

- **Só SUS:** não inclui saúde suplementar nem internações particulares.
- **Valor aprovado ≠ custo econômico:** reflete a remuneração da Tabela SUS (mais incentivos e complementos
  federais) e não o custo real do hospital. Não inclui complementações estaduais e municipais fora da AIH.
- **Local de internação ≠ residência:** UFs de referência recebem pacientes de outras UFs, o que infla o
  volume e o mix.
- **Defasagem e reapresentação:** AIH podem ser reapresentadas, e os meses recentes mudam após novas cargas.
- **Mudanças de tabela:** reajustes do SIGTAP criam saltos de nível que não são variações de eficiência.
- **Valores nominais:** para comparar anos, deflacione (por exemplo, IPCA). Ver próximos passos.
