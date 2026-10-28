# Primeira simulação na instalação Linux — 28/10/2026

A estratégia de referência de `run_replay.py` não gerou entradas no histórico
avaliado. Isso não demonstra rentabilidade, risco baixo nem funcionamento da
estratégia operacional completa `agent_pullback_timestral`: são fluxos distintos.
Nenhum modelo foi treinado ou promovido nesta avaliação e nenhuma ordem foi enviada.

## Protocolo

Comando executado no Linux, com código `d73b0b0`:

```bash
.venv/bin/python run_replay.py --postgres-history --timeframe M5 --validate-temporal --commission-per-million-side 35 --slippage-pips 0.2
```

O arquivo PostgreSQL foi congelado por hash antes da execução. O plano
`validation-b40c0837-50cc-4af5-9d28-27a34fac865f` usa divisão cronológica
60/20/20, configuração fixa e contas/memórias independentes em cada janela.
Os últimos 1.267 candles permanecem reservados, sem avaliação de desempenho.
Não houve ajuste de parâmetros, seleção por resultado ou abertura do holdout.
A estratégia usa H1/M30/M15/M5; a estratégia operacional usa outro fluxo,
H4/H1/M15/M5, com contexto diário e componentes de previsão.

Custos configurados: spread observado em cada candle, slippage de 0,2 pip por
execução e comissão de US$ 35 por milhão de unidades por lado. A comissão é
hipótese conservadora de pesquisa, não uma tarifa confirmada da conta demo.
O saldo inicial sintético é US$ 10.000; não corresponde ao saldo MT5.

## Resultado

| Janela | Candles | Operações encerradas | P&L simulado |
| --- | ---: | ---: | ---: |
| Desenvolvimento | 3.798 | 0 | US$ 0 |
| Validação | 1.266 | 0 | US$ 0 |
| Reserva final | 1.267 | Não avaliada | Não avaliado |

Motivos das 5.064 decisões sem operação:

| Motivo | Desenvolvimento | Validação |
| --- | ---: | ---: |
| Regime indefinido | 1.628 | 365 |
| Fora da sessão autorizada | 1.556 | 552 |
| Regime incompatível | 600 | 348 |
| Dados de mercado incompatíveis com a continuidade exigida | 2 | 1 |
| Aguardando transição de tendência | 12 | 0 |

Não houve entrada rejeitada após sinal, posição censurada ou conta simulada
bloqueada. O piso de 30 operações por janela não foi atingido. Custos realizados
e drawdown iguais a zero decorrem da ausência de operações; não validam o
modelo de execução, a lucratividade ou a segurança da política. Uma análise de
sensibilidade de custos seria inconclusiva com a mesma ausência de operações.

## Artefatos e próximo passo

Os relatórios completos, decisões, plano, hashes e HTML estão localmente em
`data/replays/validation-b40c0837-50cc-4af5-9d28-27a34fac865f/` e no journal
PostgreSQL. Dados de mercado e arquivos privados não são publicados no Git.
Os 25 testes de replay, execução simulada e separação temporal passaram.

Foi preparado separadamente contexto M5 de 60 dias: 12.279 candles e cobertura
aproximada de 99,93%, sem substituir a baseline operacional de 30 dias ou alterar
as partições desta avaliação. Isso prepara o contexto dos indicadores mais longos;
não constitui treinamento ou validação de rentabilidade.

A próxima avaliação deve auditar os bloqueios de regime/contexto e exercitar o
fluxo operacional com seu aquecimento histórico e parâmetros declarados antes
que resultados sejam observados. Não relaxar regras apenas para obter trades,
não usar a reserva final para ajustes e não iniciar negociação automática com
base nesta avaliação sem amostra. A coleta continua e a sessão permanece parada.
