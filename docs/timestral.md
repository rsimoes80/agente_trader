# Timestral no Aurelia FX

## Arquitetura incremental

Referência funcional: [Prompt Mestre V4](PROMPT_MESTRE_V4.md). PostgreSQL é o
banco oficial. O módulo não cria banco, não usa SQLite e não altera decisões,
risco, aprendizado, MT5, Dukascopy ou revisão JEV.

O coletor independente `run_timestral.py` consulta a ponte UTC existente.
`forecasting/core.py` seleciona somente candles M5 fechados, positivos,
ordenados e contíguos. A entrada inicial é **univariada: fechamento em preço**;
não há covariáveis nem retornos a reconstruir. Um intervalo ausente reinicia o
contexto, inclusive após o fim de semana; são necessárias 64 barras contíguas.
O contexto máximo padrão é 256 barras. Não há preenchimento de preços ausentes.

`forecasting/adapter.py` mantém um subprocesso local persistente. O processo usa
a API oficial `TimestralForecaster.from_pretrained` e `forecast`, carrega os
pesos uma vez, reutiliza o modelo e retorna quantis Q10/Q50/Q90. Timeout ou
excesso de RSS encerram somente esse processo. O coletor registra a falha e
tenta novamente; o observador V4 continua independente.

A mediana de cada endpoint fornece direção, retorno mediano derivado e
amplitude do intervalo. Os horizontes são 3/6/12 barras (15/30/60 minutos).
Os intervalos têm cobertura **nominal** de 80%, sem garantia de calibração Forex
e sem equivalência a probabilidade de lucro.

O campo `reference_time` é a abertura do último candle observado; `as_of` é o
instante de disponibilidade da previsão. O alvo é a abertura da barra localizada
3/6/12 posições depois dessa referência. A avaliação só ocorre no fechamento
da barra-alvo. Previsões ao vivo registradas após o fechamento do alvo não são
pontuadas. Ausência da barra-alvo mantém a avaliação pendente, sem interpolação.

## Instalação Windows 11

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-timestral-client.txt
.\install_timestral.ps1
.venv/Scripts/python.exe run_timestral.py --migrate
```

O instalador mantém o ambiente `.venv-timestral` separado do MT5. Baixa o modelo
`mistralai/Timestral-209M`, resolve uma revisão imutável e salva o cache em
`data/models/timestral`, fora do Git. `vendor/timestral` contém o clone oficial
nesta instalação, também ignorado; as instalações seguintes usam o pacote VCS
fixado em `requirements-timestral.txt`. O código oficial é Apache-2.0; os pesos
possuem licença Modified MIT própria, incluída no download.

Instalação inicial validada com Python 3.14, SDK 1.0.0, PyTorch CPU 2.14.1 e
Windows 11. Não foi identificada GPU CUDA neste equipamento. Para GPU, passe
ao instalador `-TorchIndexUrl` com o índice CUDA apropriado à instalação PyTorch
e ao driver, seguindo o [seletor oficial PyTorch](https://pytorch.org/get-started/locally/).
`device=auto` escolhe CUDA quando a instalação a oferece; CPU é o fallback
configurável. Falhas de GPU não alteram as decisões do V4.

## WSL2 Ubuntu

Na cópia existente do projeto dentro do WSL, com Python 3.10 ou posterior:

```bash
python3 -m venv .venv-timestral
.venv-timestral/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-timestral/bin/pip install -r requirements-timestral.txt
.venv-timestral/bin/python install_timestral_model.py
.venv/bin/pip install -r requirements-timestral-client.txt
.venv/bin/python run_timestral.py --migrate
.venv/bin/python run_timestral.py
```

Configure PostgreSQL pelo mecanismo existente. A ponte Windows deve ser
acessível pela URL configurada com `--url`. WSL não abre um terminal MT5 local.
Não foi executado teste em WSL nesta entrega. A VM atual tem apenas 1,6 GB de
RAM: nela rodam a API e as consultas, sem instalar PyTorch ou carregar 209M.

## Configuração

`data/timestral.json` é privado e ignorado pelo Git. O download preserva a
opção `enabled`; uma nova instalação começa desativada. Exemplo sem caminhos:

```json
{
  "enabled": false,
  "model": "mistralai/Timestral-209M",
  "device": "auto",
  "cpu_fallback": true,
  "timeframe": "M5",
  "horizons": [3, 6, 12],
  "mode": "observe_only",
  "context": 256,
  "min_context": 64,
  "timeout_seconds": 45,
  "load_timeout_seconds": 180,
  "memory_mb": 4096,
  "threads": 2,
  "local_files_only": true
}
```

O instalador acrescenta revisão e cache. Variáveis `TIMESTRAL_ENABLED`,
`TIMESTRAL_MODEL`, `TIMESTRAL_DEVICE`, `TIMESTRAL_TIMEFRAME`,
`TIMESTRAL_HORIZONS`, `TIMESTRAL_MODE` e equivalentes dos demais campos têm
prioridade sobre JSON. Nunca altere `revision` durante uma comparação.

Ative `enabled=true` para observação. Execute `run_timestral.py --once` para
diagnóstico ou `run_timestral.py` para coleta contínua. No Windows,
`install_timestral_startup.ps1` registra a tarefa `AgenteTrader-Timestral` no
logon do usuário. O supervisor tenta novamente após falha. O lease PostgreSQL
impede dois coletores ao vivo simultâneos. São necessários Windows e MT5
conectados para receber novos candles. Não há API paga.

Para desativar, use `enabled=false` e encerre/reinicie somente a tarefa
Timestral. Uma instância já em execução lê a configuração no próximo início.
O restante do Aurelia FX continua funcionando. Nenhum peso é armazenado no banco.

## PostgreSQL

`ForecastRepository` reutiliza `PostgresMemory.pool`, consultas parametrizadas
e transações Psycopg; o projeto não usa ORM. A extensão possui migration própria
versionada/checksum, serializada por advisory lock. As tabelas novas são:

- `timestral_model_registry`: modelo, revisão, SHA256 do peso, SDK e configuração.
- `timestral_predictions`: entradas rastreáveis, timestamps TIMESTAMPTZ,
  horizonte, preços/quantis, regime, latência e chave idempotente.
- `timestral_evaluations`: FK única por previsão, preço observado, erros,
  direção, cobertura, pinball loss e comparação com baselines constante/drift.
- `timestral_schema_migrations`: versão e checksum da extensão.

Triggers impedem atualização, exclusão ou truncamento das três tabelas de dados.
A chave natural separa mercado ao vivo de cada execução de replay, fonte,
instante, horizonte, modelo e configuração. Um lote grava os três horizontes
ou nada. Revisões dos dados não sobrescrevem a previsão original.

A migration `001_timestral.down.sql` serve somente para rollback de teste sem
previsões históricas; rejeita rollback se já existirem previsões. A validação
usa schema exclusivo em transação PostgreSQL desfeita por rollback, na instância
existente. Não há criação ou alteração das tabelas operacionais.

## Replay e porta V4

```powershell
.venv/Scripts/python.exe run_replay.py --csv CAMINHO.csv --timestral --validate-temporal
```

Por padrão, emite uma previsão a cada 12 barras para limitar custo de pesquisa;
avalia resultados a cada barra. Usa somente o prefixo histórico disponível,
em transação própria depois da decisão V4. As partições não compartilham
contexto; o holdout final não é acessado com Timestral. `--db` não é aceito
com `--timestral`.

O relatório adiciona contagens de previsões/avaliações; as métricas ficam no
PostgreSQL, separadas por origem, modelo, horizonte e regime. A porta opcional
`ForecastRepository.optional_evidence(scope, source_id, as_of)` permite consulta
com corte temporal explícito; nenhum gate operacional a utiliza nesta versão.
Não há promoção, fine-tuning ou novas features no learner.

Compare `decision_digest` e `execution_digest` entre baseline e observação
Timestral para verificar preservação do comportamento. Estudos econômicos com
uso decisório exigem protocolo separado, custos e aprovação. O corte de treino
do modelo externo e eventual sobreposição com mercados históricos não são
auditáveis aqui; resultados de replay não provam independência de pré-treino.

## Dashboard e diagnóstico

Seção **Previsão IA — Timestral** no gráfico EUR/USD e no diagnóstico de regimes.
`GET /api/diagnostics/timestral?scope=live` lê previsões e métricas do PostgreSQL.
`scope=replay` separa pesquisa; `source_id` permite escolher uma execução.
O gráfico M5 mostra os endpoints 15/30/60 minutos com linhas de ligação e
intervalo nominal; essas ligações não são previsões adicionais entre endpoints.
Previsões atrasadas não são sobrepostas ao gráfico atual.

Ausência de histórico exibe “Dados insuficientes”. Sem avaliações suficientes,
o painel informa a ausência de resultados, sem inventar acurácia.
Logs locais: `data/timestral-engine.log` e `data/timestral-supervisor.*.log`.

## Testes

```powershell
$env:PYTHONPATH='src'
.venv/Scripts/python.exe -m unittest discover -s tests -q
$env:TIMESTRAL_TEST_POSTGRES='1'
$env:TIMESTRAL_TEST_MODEL='1'
.venv/Scripts/python.exe -m unittest tests.unit.test_timestral_postgres -q
```

Testes unitários não baixam pesos. Os dois últimos flags habilitam os testes
opcionais com banco e modelo verdadeiro já instalado. Não fecham o MT5 nem
enviam ordens. Ver [evidências da entrega](timestral_validation.md).

Referências: [repositório oficial](https://github.com/mistralai/timestral),
[API implementada](https://github.com/mistralai/timestral/blob/a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff/src/timestral/forecaster.py),
[modelo e licença dos pesos](https://huggingface.co/mistralai/Timestral-209M).
