# Integração com NautilusTrader

## O que foi instalado

- Fonte clonada em `nautilus_trader/` a partir do repositório informado, branch `master`.
- Ambiente virtual isolado em `.venv/` (Python 3.14).
- Wheel `nautilus_trader==2.0.0rc7` instalada nesse ambiente, correspondente à versão indicada no `python/pyproject.toml` do clone.

O código está em fase 2.0 release candidate. A documentação oficial não recomenda a linha pre-release para produção controlando capital real. O motor desta aplicação, por isso, mantém execução live desativada.

## Encaixe arquitetural

O NautilusTrader separa estratégia dos protocolos de venue por adapters: clientes de dados, execução, instrumentos e factories registram um provedor comum. Estratégia e gerenciamento de ordens podem então operar sobre modelos normalizados. A integração é útil para substituir a simulação por um runtime de eventos sem embutir chamadas REST/WebSocket de uma corretora dentro da estratégia.

Para Forex, Interactive Brokers é o ponto inicial mais viável no clone: há adapter oficial de dados e execução, conexão via TWS/IB Gateway e instrumentos de moedas. A autenticação operacional usa uma sessão de TWS/IB Gateway; o host/porta/client ID da tela são configuração do socket, não uma API key da corretora. O adapter oficial não é um conector OANDA genérico.

O `ADAPTERS.md` do repositório lista MetaTrader 5 como adapter comunitário, fora do núcleo oficial. Para outras corretoras, deve ser implementado e mantido um adapter compatível ou plugin separado; guardar campos de API key/secret no painel não cria compatibilidade por si só.

## Próximo caminho de integração

1. Definir `BrokerAdapter` interno para conectar, carregar especificação do par, fornecer bid/ask/barras, consultar conta/posições, submeter/cancelar ordens e reconciliar o estado.
2. Criar um adapter de paper que use as mesmas mensagens e eventos antes de ligar a interface a qualquer execução live.
3. Mapear os eventos do Nautilus (`Instrument`, quotes/bars, `Order`, `Position`, fills) para o contrato interno e testar feed, desconexão, retry, duplicidade, ordem parcial e estado após reinício.
4. Implementar primeiro IB/TWS em conta paper. A estratégia precisa receber preço bid/ask e metadados exatos do contrato; sizing precisa valor do pip, moeda da conta, margem, mínimo de lote e passos do broker.
5. Só depois de backtests fora da amostra, replay de eventos, reconciliação de ordens e revisão do kill switch deve ser considerado um modo live explicitamente separado.

## Estado do projeto

A sessão Dukascopy FIX de leitura está implementada fora do runtime NautilusTrader em `dukascopy_feed.py`; ela fornece bid/ask e candles ao vivo, sem enviar ordens. O adapter NautilusTrader de execução segue sem implementação. IB, MT5 e plugins genéricos permanecem apenas descritos/configuráveis, sem sessões ativas.

## Fontes oficiais

- [Repositório NautilusTrader](https://github.com/nautechsystems/nautilus_trader)
- [Guia oficial de adapters](https://nautilustrader.io/docs/latest/concepts/adapters/)
- [Integração oficial Interactive Brokers](https://nautilustrader.io/docs/latest/integrations/interactive_brokers/)
- [Matriz de adapters](https://github.com/nautechsystems/nautilus_trader/blob/master/ADAPTERS.md)
- [Modelo de instrumentos e CurrencyPair](https://nautilustrader.io/docs/latest/concepts/instruments/)
