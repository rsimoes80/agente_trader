# Replay causal do EUR/USD

O comando `run_replay.py` integra a fundação do agente: validação de candles, sessões com timezone, observação, estrutura, recuperação de experiências, hipótese, contrato de expectativa, comparação com candles posteriores, veto de risco, decisão e memória SQLite. Cada candle gera uma decisão, inclusive durante a espera. A estratégia experimental é identificada como `research_breakout_retest`, versão `1.0`.

## Executar

No Windows, dentro do projeto:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-replay.txt
.venv/Scripts/python.exe run_replay.py --capture-mt5 --timeframe M5 --count 1500
```

A captura utiliza o terminal local conectado e exclui o candle em formação. O CSV capturado fica em `data/replay_inputs/`, acompanhado de metadados sem informações da conta. Depois da captura, o replay funciona com o terminal fechado.

Para repetir exatamente o histórico salvo:

```powershell
.venv/Scripts/python.exe run_replay.py --csv data/replay_inputs/ARQUIVO.csv --timeframe M5 --source mt5_local_closed_bars
```

No Linux, o processamento de CSV funciona sem MetaTrader5, NumPy ou pandas. Instale o pacote de timezones do sistema ou `tzdata` quando necessário e execute `python3 run_replay.py ...`.

## Entrada e relógio

O CSV precisa conter `timestamp,open,high,low,close`. `volume` e `spread_pips` são opcionais. O spread ausente permanece desconhecido e impede a aprovação de risco; não é substituído por zero. Os timestamps precisam conter offset, indicar a **abertura** do candle e estar alinhados ao timeframe informado. O relógio da decisão é a abertura mais a duração do timeframe: apenas então o candle completo fica disponível. O usuário deve confirmar que seu CSV realmente contém candles fechados e usa esse formato temporal.

Exemplo de linha, apenas para ilustrar o formato:

```csv
timestamp,open,high,low,close,volume,spread_pips
2026-10-19T08:00:00+00:00,1.10000,1.10040,1.09990,1.10020,100,0.8
```

Candles inválidos, duplicados ou fora de ordem rejeitam o dataset antes do replay; os dados não são ordenados nem corrigidos silenciosamente. Uma lacuna inesperada durante o horário semanal do Forex cancela a hipótese, registra `INVALID_MARKET_DATA` e reinicia o contexto. A convenção de fechamento semanal é sexta às 17h até domingo às 17h de Nova York; não substitui o calendário de feriados da corretora. Interrupções por feriado serão bloqueadas conservadoramente.

## Hipótese experimental

Depois de pelo menos 30 candles, a estrutura anterior precisa ter dois topos e dois fundos confirmados em progressão. O fechamento cruza o último swing na direção da estrutura. Esse rompimento cria uma hipótese com região, stop e prazo congelados. Um candle posterior deve retornar à região; outro candle posterior deve fechar além do extremo do candle de retorno. A formação da hipótese nunca se confirma no mesmo candle.

O toque no stop, a expiração após 12 períodos, uma mudança de sessão ou uma falha de dados encerra a hipótese. IDs encerrados não voltam a gerar sinais. O fim do dataset deixa contratos pendentes como `insufficient_data`, sem supor confirmação, invalidação ou resultado financeiro.

As sessões padrão são Londres (08h–17h local) e Nova York (08h–17h local), em dias úteis e com horário de verão. Londres tem prioridade durante a sobreposição. A autorização usa o instante da decisão, no fechamento do candle: um gatilho que fecha exatamente no fim da sessão já não pode autorizar entrada nessa sessão. Esses horários são parâmetros de pesquisa, não horários oficiais de abertura de uma bolsa Forex.

O sinal hipotético só aparece depois do veto independente de risco. Os padrões de pesquisa são conta sintética USD 10.000, risco de 0,5%, spread máximo de 2 pips, slippage de 0,2 pip, recompensa bruta de 2,5 vezes a distância ao stop e relação líquida mínima de 2. No máximo cinco sinais são aceitos por dia UTC. Os parâmetros ficam no manifesto de cada execução; o CLI não lê credenciais nem o saldo da conta MT5.

Os conceitos dos livros continuam no catálogo com sua proveniência e estado de revisão. Não são importados como regras de entrada desta estratégia experimental.

## Memória, reprodução e relatório

O banco padrão é `data/agent_memory.sqlite3`. Snapshots, decisões, experiências e eventos são persistidos com IDs, relógio histórico e hashes. Triggers bloqueiam UPDATE/DELETE dos registros pelo fluxo normal da aplicação. O fechamento explícito das conexões permite reabrir o banco no Windows.

A recuperação automática consulta somente observações da própria execução com timestamp estritamente anterior ao candle atual. Isso impede que repetir o mesmo dataset duplique a amostra consultada ou que uma execução anterior forneça informação sobre o futuro do replay. O histórico de todas as execuções permanece persistente para revisão e para um futuro protocolo explícito de memória externa, com corte temporal, deduplicação e versionamento. A quantidade de observações semelhantes não é uma quantidade de trades independentes e não produz uma probabilidade de sucesso.

Cada execução recebe um ID novo e gera, em `data/replays/<run_id>/`:

- `manifest.json`: fonte declarada, hash do dataset, configuração, versões e política de memória.
- `candles.jsonl`: cópia normalizada e rastreável dos candles utilizados.
- `decisions.jsonl`: todas as decisões e seus motivos, hipótese, risco e amostra recuperada.
- `transitions.json`: transições de estado com relógio do replay.
- `report.json` e `report.html`: contagens, limitações e tabela das decisões. Abra o HTML diretamente no navegador.

O `decision_digest` ignora o namespace aleatório da execução e permite comparar o conteúdo das decisões. Com o mesmo dataset, fonte, configuração e código, ele deve ser idêntico mesmo após reiniciar o processo e reutilizar o banco. Manifestos e artefatos `started`, `completed` ou `failed` permitem distinguir execuções completas de registros parciais após falha. Uma falha de persistência interrompe o replay; não há retry que duplique decisões.

## Alcance desta etapa

Este replay valida o encadeamento causal e a persistência. Não simula preenchimento, comissões, P&L, MAE/MFE ou evolução do saldo. Stop e alvo são planos hipotéticos; `result_in_r` e `net_pnl` permanecem nulos. Não há evidência de rentabilidade nem validação HTF/LTF neste estágio. O próximo passo de pesquisa é um simulador de execução e avaliação de resultados com custos, datasets separados e validação temporal. A integração ao monitor web é uma etapa posterior.

## Verificação

```powershell
$env:PYTHONPATH='src'
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

A suíte usa candles sintéticos explicitamente identificados, exercita confirmação, veto por spread, invalidação, expiração, falha de dados, persistência, bloqueio de alteração do journal e reprodução. A alteração de candles futuros precisa preservar todas as decisões anteriores.
