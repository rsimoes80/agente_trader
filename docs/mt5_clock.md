# Horário e recuperação do MT5

O contrato `mt5-utc-v1` entrega candles e ticks em UTC, preservando o epoch
original e o deslocamento aplicado. O consumidor valida esse contrato antes de
gravar observações. Não aplica uma segunda conversão.

Para ThinkMarkets, o perfil de fechamento de Nova York usa GMT+2/GMT+3 conforme
a data de cada candle. A interpretação precisa ser confirmada por ticks recentes
que avançam junto com o relógio UTC. APIs que já entregam UTC permanecem em UTC.
Fontes desconhecidas não recebem uma correção arbitrária de três horas.

A [ThinkMarkets documenta GMT+2/GMT+3](https://support.thinkmarkets.com/hc/en-gb/articles/11613703690385-What-is-ThinkMarkets-server-time).
O perfil é específico da corretora e falha de forma explícita se os ticks não
confirmarem a política esperada. Labels ambíguos na mudança de horário são rejeitados.

O cache `data/mt5_clock_state.json` é local, atômico e vinculado ao servidor e
à corretora. Reiniciar a ponte não exige configuração manual. Cotações antigas
não autorizam novas observações. Falhas do terminal, histórico em carregamento,
relógios divergentes e fonte sem contrato suspendem a coleta e são tentados novamente.
O checkpoint é vinculado ao relógio validado; checkpoints legados não são reutilizados.

## Inicialização

Execute `install_mt5_bridge_startup.ps1` para registrar a tarefa Windows
`AgenteTrader-MT5Bridge` no logon do usuário. O supervisor reinicia a ponte se ela
encerrar. O terminal MT5 precisa estar aberto e conectado nesse Windows.
Na VM, `agente-trader-diagnostics.service` inicia automaticamente e reconecta.
Não são enviadas ordens.

## Histórico e testes

Registros antigos são preservados. Replays sem contrato UTC são identificados
como legados e não são elegíveis para novos experimentos de parâmetros.
Novas capturas têm metadados de relógio e hash do CSV, preservados nas partições.

Os testes cobrem verão/inverno, transições de horário, API já em UTC, cache e
reinicialização, terminal fechado/reaberto, histórico temporariamente indisponível,
fonte diferente, timestamps futuros, relógios divergentes e duplicação de candles.
Fechar/reabrir o terminal é simulado, sem interferir no MT5 usado pelo usuário.
