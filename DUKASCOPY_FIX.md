# Feed ao vivo da Dukascopy

## Escopo implementado

O adaptador `dukascopy_feed.py` abre uma sessão TLS/FIX 4.4 dedicada ao canal de dados. Ele autentica, responde a heartbeats, assina um único par Forex e lê bid/ask de mensagens `MarketDataSnapshotFullRefresh` (`35=W`). A assinatura usa `MarketDataRequest` (`35=V`) e o símbolo configurado, como `EUR/USD`.

As cotações são convertidas em candles pelo timeframe escolhido no painel. O OHLC usa o preço médio entre bid e ask. O campo `volume` usado pelos filtros de volume é a contagem de atualizações de cotação do provedor; isso é apenas volume de ticks, não volume consolidado negociado no mercado Forex. O spread atual é mostrado no painel e candidatos acima do limite configurado são vetados.

A estratégia roda quando um candle fecha, não em cada tick. Com os parâmetros iniciais, o indicador mais longo exige 61 candles fechados. No M5 isso leva pouco mais de cinco horas após conectar; M15/H1 exigem aquecimento proporcionalmente maior. Pausas maiores que dois candles reiniciam o aquecimento para não misturar barras separadas por uma interrupção longa.

## Configurar

1. A Dukascopy precisa habilitar FIX API na conta JForex demo e informar os dados de sessão.
2. Libere o IP de saída deste computador junto à corretora, conforme o manual.
3. Em **Corretoras**, preencha host, porta, `TargetCompID`, `SenderCompID` específico do feed, usuário e senha FIX. Não use a senha normal do JForex.
4. Salve os dados cifrados pelo DPAPI do Windows e use **Conectar feed Dukascopy** no painel principal.
5. Aguarde o aquecimento dos candles. A tela indica cotações, spread, contagem de candles e decisão técnica.

Cada alteração de instrumento ou timeframe desconecta a sessão para impedir análise de um ativo diferente daquele assinado. Conecte novamente depois de alterar.

## Jev e ordens

O Jev pode revisar automaticamente candidatos técnicos se uma chave TypeSafe estiver configurada e a caixa de revisão automática estiver marcada. Cada candidato fechado pode consumir uma chamada/crédito TypeSafe. Sem a caixa marcada, os dados da conta/feed não são enviados ao Jev.

O adaptador não constrói nem transmite `NewOrderSingle` (`35=D`). A conta permanece em demonstração, a aplicação não envia ordens e o sinal na tela significa apenas candidato técnico ou veto do Jev. Histórico de candles e dados anteriores não são baixados pela FIX API; este fluxo não usa backtest histórico.

## Restrições operacionais

- O feed pode ficar sem cotação durante fechamento de mercado ou interrupção de rede.
- É necessário sincronizar o relógio da máquina com UTC/GMT e manter o IP autorizado.
- A estratégia usa preço médio dos lados; não simula execução, slippage, margem ou conversão de moedas nesse fluxo.
- A sessão e o parser cobrem somente o subconjunto FIX necessário a cotações, heartbeat, logon, logout e erros da assinatura. Mensagens de negociação continuam fora do caminho ativo.
- Se a senha de demonstração for recusada, a corretora encerrar a sessão ou não chegarem bid/ask, o painel mostra erro e nenhuma decisão é executada.
