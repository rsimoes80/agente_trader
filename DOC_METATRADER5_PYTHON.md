# Referência de integração Python com MetaTrader 5

Resumo em português da [documentação oficial “MetaTrader para Python” da MQL5](https://www.mql5.com/pt/docs/python_metatrader5) e de todos os links de função do menu lateral. A página descreve o pacote `MetaTrader5`, que conversa com um terminal MetaTrader 5 local por comunicação entre processos. Ela não descreve uma API remota independente do terminal.

> Este documento é um guia de consulta, não uma cópia literal. As assinaturas e descrições resumem a referência oficial; consulte os links oficiais abaixo para detalhes e mudanças de versão. As operações de negociação podem enviar ordens à corretora.

## Visão geral da página

A MetaQuotes apresenta o pacote Python como forma de obter dados do terminal para análise estatística, automação e aprendizado de máquina. A instalação indicada na página é:

```powershell
python -m pip install MetaTrader5
python -m pip install --upgrade MetaTrader5
```

O exemplo oficial cobre inicialização, estado/versão do terminal, captura de ticks e barras por diferentes métodos, encerramento da conexão e visualização com pandas/matplotlib. A página lista as 32 funções documentadas neste guia.

## Conceitos comuns

- **Terminal local:** o pacote se conecta ao executável instalado do MT5. Em geral, terminal e biblioteca precisam estar disponíveis na mesma máquina Windows e com arquitetura compatível.
- **Símbolo:** use o nome exatamente como aparece na corretora/Market Watch; podem existir sufixos, prefixos ou nomes específicos do broker.
- **Retorno e erros:** várias funções retornam `None` ou `False` em falha. Consulte `last_error()` imediatamente após a falha, pois ele informa o último erro da biblioteca.
- **Dados históricos:** o terminal limita barras ao histórico disponível e à opção “Máximo de barras no gráfico”. Horários usados na consulta devem ser tratados com cuidado; a documentação alerta para UTC nas consultas de barras/ticks por data.
- **Estruturas retornadas:** resultados costumam ser tuplas nomeadas ou arrays NumPy estruturados. `_asdict()` transforma tuplas nomeadas em dicionário; `pandas.DataFrame(...)` facilita inspeção e processamento.
- **Segredos:** evite gravar senhas em código, logs ou histórico do shell. Use contas de demonstração para desenvolvimento.

## Conexão e diagnóstico

### `initialize`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5initialize_py)

```python
mt5.initialize(path=None, login=..., password="...", server="...", timeout=60_000, portable=False)
```

Inicializa e conecta ao terminal. Sem argumentos, tenta localizar o terminal e usar a última conta. `path` é o caminho do executável; `login`, `password` e `server` selecionam a conta; `timeout` é em milissegundos (padrão documentado: 60.000); `portable` ativa o modo portátil. Retorna `True` em sucesso e `False` em falha. O terminal pode ser iniciado automaticamente. Verifique `last_error()` se falhar.

### `login`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5login_py)

```python
mt5.login(login, password="...", server="...", timeout=60_000)
```

Autentica em outra conta usando uma conexão inicializada. O número da conta é obrigatório; senha e servidor podem ser omitidos quando já estão armazenados no terminal. `timeout` é em milissegundos. Retorna booleano.

### `shutdown`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5shutdown_py)

```python
mt5.shutdown()
```

Encerra a conexão Python com o terminal. Use em um bloco `finally` para garantir limpeza mesmo quando ocorrer uma exceção. Não retorna dados úteis.

### `version`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5version_py)

```python
mt5.version()
```

Retorna informações de versão do terminal conectado, tipicamente uma tupla com número de build, versão e data. Retorna `None` se não for possível consultar.

### `last_error`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5lasterror_py)

```python
mt5.last_error()
```

Retorna código e descrição do último erro da biblioteca Python. Chame logo após detectar `False` ou `None`; uma chamada posterior pode deixar de representar a falha original.

### `account_info`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5accountinfo_py)

```python
mt5.account_info()
```

Retorna as propriedades da conta atual em uma tupla nomeada (ou `None` em falha). Inclui identificador, servidor, moeda, alavancagem, saldo, crédito, lucro flutuante, equity, margem, margem livre e flags/permissões de negociação. Trate essas informações como sensíveis.

### `terminal_info`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5terminalinfo_py)

```python
mt5.terminal_info()
```

Retorna estado e propriedades do terminal em uma tupla nomeada: informações como caminho, build, conexão, permissões de negociação, modo DLL e opções locais. Retorna `None` em falha.

## Símbolos e livro de ofertas

### `symbols_total`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5symbolstotal_py)

```python
mt5.symbols_total(group="*")
```

Retorna a quantidade de símbolos na base do terminal; o filtro `group` é opcional e usa máscaras/grupos de símbolos. Retorna `-1` em falha. Não confunda com o número de símbolos já selecionados no Market Watch.

### `symbols_get`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5symbolsget_py)

```python
mt5.symbols_get(group="*", name=None)
```

Obtém símbolos como uma sequência de estruturas `SymbolInfo`. Pode filtrar por `group` (máscara) ou por `name`. Retorna `None` em falha; uma sequência vazia pode significar que o filtro não encontrou correspondências.

### `symbol_info`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5symbolinfo_py)

```python
mt5.symbol_info(symbol)
```

Retorna propriedades do instrumento em `SymbolInfo`, ou `None` se não existir/ocorrer falha. Inclui `digits`, `point`, bid/ask, spread, moedas base/lucro/margem, tamanho e valor do tick, tamanho do contrato, limites de volume (`volume_min`, `volume_max`, `volume_step`), modo de cálculo e restrições de negociação. Use esses metadados em vez de assumir regras fixas de pip, lote ou preço.

### `symbol_info_tick`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5symbolinfotick_py)

```python
mt5.symbol_info_tick(symbol)
```

Retorna o tick mais recente (`Tick`) com bid, ask, last, volume, horário em segundos/milissegundos e flags. Retorna `None` se não houver cotação válida ou houver falha. Pode ser necessário selecionar o símbolo primeiro.

### `symbol_select`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5symbolselect_py)

```python
mt5.symbol_select(symbol, enable=True)
```

Adiciona ou remove o símbolo do Market Watch. `enable=True` seleciona; `False` tenta removê-lo. Não é possível removê-lo enquanto houver gráfico aberto ou posição baseada nele. Retorna booleano.

### `market_book_add`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5marketbookadd_py)

```python
mt5.market_book_add(symbol)
```

Assina atualizações do livro de ofertas para o símbolo. Retorna booleano. A disponibilidade e profundidade dependem do instrumento, terminal e provedor.

### `market_book_get`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5marketbookget_py)

```python
mt5.market_book_get(symbol)
```

Obtém a fotografia atual do livro após a assinatura, como sequência de `BookInfo` (tipo, preço, volume e volume real quando fornecido). Retorna `None` em falha/indisponibilidade. Não é um fluxo de eventos Python por si só; consulte novamente para obter o estado atual.

### `market_book_release`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5marketbookrelease_py)

```python
mt5.market_book_release(symbol)
```

Cancela a assinatura do livro do símbolo. Retorna booleano. Libere a assinatura ao terminar o consumo.

## Barras e ticks históricos

As três funções `copy_rates_*` retornam normalmente um array NumPy estruturado com `time`, `open`, `high`, `low`, `close`, `tick_volume`, `spread` e `real_volume`. `time` é o horário de abertura da barra em segundos desde epoch. As consultas históricas usam o histórico disponível no terminal.

### `copy_rates_from`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5copyratesfrom_py)

```python
mt5.copy_rates_from(symbol, timeframe, date_from, count)
```

Busca até `count` barras, incluindo as barras cuja abertura seja anterior ou igual a `date_from`; a referência explica a ordenação temporal do conjunto retornado. `timeframe` é uma constante `TIMEFRAME_*`. Use `datetime` UTC para alinhar a consulta ao horário de mercado esperado. Resultado vazio/`None` deve ser verificado.

### `copy_rates_from_pos`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5copyratesfrompos_py)

```python
mt5.copy_rates_from_pos(symbol, timeframe, start_pos, count)
```

Busca barras por posição relativa à barra atual: posição `0` é a barra corrente (ainda em formação), `1` é a barra anterior e assim por diante. Use `start_pos=1` quando a estratégia só puder consumir candles fechados. Retorna array de barras ou `None`.

### `copy_rates_range`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5copyratesrange_py)

```python
mt5.copy_rates_range(symbol, timeframe, date_from, date_to)
```

Obtém as barras cuja abertura esteja dentro do intervalo solicitado, incluindo os limites definidos na referência. `date_from` e `date_to` devem ser datetimes coerentes em UTC. Retorna array NumPy ou `None`.

### `copy_ticks_from`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5copyticksfrom_py)

```python
mt5.copy_ticks_from(symbol, date_from, count, flags)
```

Obtém até `count` ticks a partir do horário indicado. `flags` define quais campos/eventos incluir: `COPY_TICKS_INFO`, `COPY_TICKS_TRADE` ou `COPY_TICKS_ALL`. Os registros podem conter `time`, `bid`, `ask`, `last`, `volume`, `time_msc`, `flags`, `volume_real`. Datas devem ser tratadas em UTC.

### `copy_ticks_range`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5copyticksrange_py)

```python
mt5.copy_ticks_range(symbol, date_from, date_to, flags)
```

Obtém os ticks entre os dois horários usando o filtro `flags` descrito acima. Retorna array estruturado ou `None`. Intervalos longos podem gerar muitos dados; processe em blocos e confirme o fuso horário antes de comparar com outras fontes.

### Constantes de timeframe e ticks

Os intervalos são passados por constantes como `mt5.TIMEFRAME_M1`, `TIMEFRAME_M5`, `TIMEFRAME_H1` e `TIMEFRAME_D1`. Para ticks, as flags documentadas são `mt5.COPY_TICKS_INFO`, `mt5.COPY_TICKS_TRADE` e `mt5.COPY_TICKS_ALL`. Prefira constantes do pacote em vez de números mágicos.

## Ordens ativas e cálculo prévio

### `orders_total`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5orderstotal_py)

```python
mt5.orders_total()
```

Retorna o número de ordens pendentes ativas no terminal, ou `None` em falha. Ordens pendentes não são o mesmo que posições abertas.

### `orders_get`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5ordersget_py)

```python
mt5.orders_get(symbol=None, ticket=None, group=None)
```

Retorna ordens pendentes ativas, filtradas por símbolo, ticket ou grupo. A referência orienta usar um filtro por chamada. Retorna tupla de `TradeOrder` ou `None` em falha; sequência vazia significa nenhuma ordem correspondente. O filtro `group` aceita máscaras de símbolos.

### `order_calc_margin`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5ordercalcmargin_py)

```python
mt5.order_calc_margin(action, symbol, volume, price)
```

Estima a margem na moeda da conta para o tipo de ordem, símbolo, volume e preço informados. `action` é constante `ORDER_TYPE_*`. Retorna valor numérico ou `None`. O cálculo usa as condições atuais e não incorpora as posições e ordens pendentes existentes; não substitui a checagem final de margem.

### `order_calc_profit`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5ordercalcprofit_py)

```python
mt5.order_calc_profit(action, symbol, volume, price_open, price_close)
```

Calcula lucro/prejuízo estimado na moeda da conta para uma compra ou venda entre preços dados. `action` deve ser `ORDER_TYPE_BUY` ou `ORDER_TYPE_SELL`. Retorna número ou `None`. É útil para sizing e análise de risco, mas não garante o resultado após spread, comissão, swap, slippage ou execução parcial.

### `order_check`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5ordercheck_py)

```python
mt5.order_check(request)
```

Verifica se a solicitação de negociação está bem formada e se há fundos/condições para executá-la. `request` é um dicionário de campos `MqlTradeRequest`, por exemplo ação, símbolo, volume, tipo, preço, SL/TP, desvio, preenchimento, validade e comentário, conforme a operação. Retorna `OrderCheckResult` com código/comentário e valores de saldo/margem projetados, ou `None` em falha da chamada. Aprovação aqui não garante que `order_send` será executado: preço e estado podem mudar.

### `order_send`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5ordersend_py)

```python
mt5.order_send(request)
```

Envia uma solicitação de negociação ao servidor. O argumento é um dicionário compatível com `MqlTradeRequest`; os campos variam conforme a ação (negócio, ordem pendente, modificação ou remoção). Para ordem de mercado são comuns `action`, `symbol`, `volume`, `type`, `price`, `sl`, `tp`, `deviation`, `magic`, `comment`, `type_time` e `type_filling`. Retorna `OrderSendResult` com `retcode`, descrição, tickets, volume/preço executados e dados da solicitação; `None` indica erro de chamada. **Sempre valide o `retcode`**: receber um objeto de resultado não significa que a ordem foi executada. Faça `order_check`, trate rejeição, execução parcial e duplicidade, e reconcilie posições/ordens após enviar.

## Posições abertas

### `positions_total`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5positionstotal_py)

```python
mt5.positions_total()
```

Retorna o número de posições abertas, ou `None` em falha. Posições representam exposição executada; ordens pendentes são consultadas separadamente.

### `positions_get`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5positionsget_py)

```python
mt5.positions_get(symbol=None, ticket=None, group=None)
```

Obtém posições abertas, com filtro opcional por símbolo, ticket ou grupo. Retorna tupla de `TradePosition`, `None` em erro ou sequência vazia quando não há correspondências. As posições incluem lado/tipo, volume, preço de abertura, SL/TP, lucro e identificadores necessários para reconciliação.

## Histórico de ordens e negócios

### `history_orders_total`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5historyorderstotal_py)

```python
mt5.history_orders_total(date_from, date_to)
```

Conta ordens históricas no intervalo de datas. Retorna quantidade ou `None` em falha. Use datas UTC e intervalo explícito.

### `history_orders_get`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5historyordersget_py)

```python
mt5.history_orders_get(date_from, date_to, group=None, ticket=None, position=None)
```

Obtém ordens históricas por período e, conforme a variante, filtra por ticket de ordem ou identificador de posição; a referência também documenta `group` para filtrar símbolos. Retorna registros `TradeOrder` ou `None`. Diferencie ordens canceladas/rejeitadas de ordens que geraram negócios.

### `history_deals_total`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5historydealstotal_py)

```python
mt5.history_deals_total(date_from, date_to)
```

Conta negócios (deals) no intervalo. Um negócio é um evento de execução, não necessariamente uma operação completa de entrada e saída. Retorna quantidade ou `None` em falha.

### `history_deals_get`

[Documentação oficial](https://www.mql5.com/pt/docs/python_metatrader5/mt5historydealsget_py)

```python
mt5.history_deals_get(date_from, date_to, group=None, ticket=None, position=None)
```

Obtém negócios no intervalo ou consulta por ticket/posição, com filtro de grupo quando aplicável. Retorna tupla de `TradeDeal` ou `None`. Use `position_id`/identificadores relacionados para agrupar execuções parciais e reconstruir o ciclo de vida da posição. Some comissão, swap, fee e lucro conforme necessário para calcular resultado líquido.

## Exemplo seguro de sessão e leitura

```python
from datetime import datetime, timezone
import MetaTrader5 as mt5

try:
    if not mt5.initialize():
        raise RuntimeError(f"initialize falhou: {mt5.last_error()}")

    symbol = "EURUSD"  # confirme o nome exato no seu broker
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"symbol_select falhou: {mt5.last_error()}")

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, 500)
    if info is None or tick is None or bars is None:
        raise RuntimeError(f"consulta falhou: {mt5.last_error()}")

    print("conta:", mt5.account_info())
    print("símbolo:", info.name, "digits:", info.digits, "volume_step:", info.volume_step)
    print("bid/ask:", tick.bid, tick.ask)
    print("barras fechadas:", len(bars))
finally:
    mt5.shutdown()
```

Este exemplo consulta apenas dados. Ele não envia ordens. Para estratégia baseada em fechamento de candle, a posição `1` evita incluir a barra `0`, que ainda pode estar em formação.

## Fluxo recomendado para uma integração

1. Inicializar o terminal e confirmar `terminal_info()`, `version()` e `account_info()`.
2. Selecionar o símbolo e validar `symbol_info()` (precisão, tick, volume mínimo/máximo/passo, modo de execução e moedas).
3. Consultar dados com UTC e descartar barras/ticks incompletos ou fora de ordem; registrar origem, símbolo, timeframe e instante de coleta.
4. Calcular volume e risco usando metadados e `order_calc_profit`; estimar margem com `order_calc_margin`.
5. Se for operar, montar e validar o pedido com `order_check`, submeter apenas após controles locais e analisar o `retcode` de `order_send`.
6. Reconciliar o resultado consultando `orders_get`, `positions_get` e histórico; não assumir que um timeout significa que nada foi executado.
7. Liberar assinaturas do livro com `market_book_release` e finalizar a sessão com `shutdown()`.

## Correspondência com este projeto

Este repositório já usa `MetaTrader5` para estado do terminal e captura histórica em [mt5_provider.py](mt5_provider.py). A documentação acima mostra APIs adicionais que podem servir para cotação, cálculo de risco, paper trading ou uma futura execução. Atualmente, a integração local do projeto está orientada à leitura e ao backtest; adicionar `order_send` seria uma mudança de escopo com risco operacional e requer desenho separado de validação, idempotência, reconciliação e kill switch.

## Fontes oficiais

- [Página principal: MetaTrader para Python](https://www.mql5.com/pt/docs/python_metatrader5)
- Funções individuais: links junto a cada seção.
- [Pacote MetaTrader5 no PyPI](https://pypi.org/project/MetaTrader5/) (instalação e versões publicadas).

**Revisado em:** 2026-10-19. A documentação online pode mudar; confirme assinatura, disponibilidade e comportamento na versão instalada do pacote/terminal.
