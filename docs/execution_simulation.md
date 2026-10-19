# Execução simulada e avaliação temporal

O replay EUR/USD agora fecha o ciclo entre sinal e resultado: envia o plano para um simulador offline, acompanha os candles seguintes e acrescenta resultados à memória. Nenhum adaptador de ordens reais é utilizado. A estratégia permanece experimental e não é ajustada automaticamente.

## Comandos

Uma execução completa, com custos e resultados:

```powershell
.venv/Scripts/python.exe run_replay.py --csv data/replay_inputs/ARQUIVO.csv --timeframe M5 --source mt5_local_closed_bars
```

Captura e avaliação temporal, preservando a janela final:

```powershell
.venv/Scripts/python.exe run_replay.py --capture-mt5 --count 1500 --validate-temporal
```

Os custos podem ser declarados explicitamente:

```powershell
.venv/Scripts/python.exe run_replay.py --csv HISTORICO.csv --validate-temporal --commission-per-million-side 35 --slippage-pips 0.2 --max-holding-bars 24
```

Após congelar a estratégia e a configuração, `--include-holdout` junto com `--validate-temporal` inclui a janela final na avaliação. O padrão deixa essa janela reservada. Repetir a avaliação com configurações ajustadas após ver seus resultados elimina a independência do holdout; o manifesto registra a solicitação, mas não consegue auditar acesso humano anterior ao dataset. Dados já inspecionados em execuções antigas não passam a ser uma amostra independente por receberem um novo nome de janela.

## Preço e preenchimento

O contrato da entrada exige OHLC de **bid**. Para CSVs, é responsabilidade de quem prepara os dados conferir essa base. O ask é reconstruído somando `spread_pips * pip_size`, com spread constante dentro de cada candle. É uma aproximação declarada: o histórico não tem toda a trajetória de bid/ask.

O sinal é decidido após um candle fechado. A entrada só pode ocorrer na abertura imediatamente seguinte e contígua. Compra usa ask mais slippage; venda usa bid menos slippage. O simulador verifica novamente sessão, expiração, spread, saldo, limites de perda/drawdown, quantidade diária de entradas, geometria stop/alvo e relação líquida de risco/recompensa. Stop e alvo permanecem congelados. Um gap que deixe a nova entrada fora desses níveis rejeita a entrada, sem mover o plano.

A quantidade é recalculada pela perda planejada até o stop, incluindo slippage de saída e comissão dos dois lados. O preço de entrada já inclui o spread/slippage de entrada; esses custos não são adicionados novamente ao dimensionamento. Não há arredondamento para lote mínimo/passo, margem ou restrições específicas da corretora: as unidades são contínuas neste modelo.

Posições compradas saem pelo bid e vendidas pelo ask. Stops executam com slippage adverso; targets são limites executados no nível definido, sem ganho adicional quando o mercado abre além do alvo. Se houver gap através do stop, usa-se a abertura piorada pelo slippage: a perda pode superar 1 R. Se stop e alvo forem tocados no mesmo candle sem que a abertura já determine a saída, assume-se **stop primeiro**. A regra é conservadora e não pretende reconstruir a ordem dos ticks.

O prazo padrão da posição é de 24 candles desde o preenchimento. Após verificar stop/alvo, o simulador encerra posições expiradas no fechamento com slippage. A última posição também é encerrada no fim da janela, usando `END_OF_DATA`, para não carregar exposição ou labels entre partições. Sinais sem abertura seguinte são rejeitados explicitamente. Sessões filtram entradas; uma posição já aberta continua sendo acompanhada até sua regra de saída.

Se faltar spread ou houver lacuna inesperada com uma posição aberta, o resultado é `censored`, com P&L desconhecido. A conta sintética fica bloqueada para novas entradas até o fim daquela execução: continuar negociando com um saldo inventado invalidaria os limites de risco. O relatório distingue o saldo conhecido das posições já encerradas de um resultado total desconhecido.

## Custos e métricas

Os padrões de pesquisa são slippage de 0,2 pip por execução de mercado e comissão de USD 35 por milhão de unidades por lado (equivalente a USD 3,50 por 100 mil unidades por lado). São hipóteses configuráveis, não tarifas verificadas da corretora. Não há swaps, financiamento, latência, liquidez parcial ou fila de ordens no modelo.

Para cada posição encerrada:

- `gross_pnl`: variação de preço medida entre referências de bid, antes dos custos.
- `spread_cost`, `slippage_cost`, `commission`: custos separados, reconciliados com os preenchimentos.
- `net_pnl = gross_pnl - spread_cost - slippage_cost - commission`.
- `result_in_r = net_pnl / initial_risk`, com o risco monetário calculado no preenchimento.
- Entrada/saída, níveis congelados, unidades, duração e motivo da saída.
- `mae_price`, `mfe_price`, `mae_r`, `mfe_r`: excursões de preço antes dos custos completos.

MAE/MFE são **limites inferiores conservadores**. Candles sobreviventes usam seus extremos completos; no candle de saída usam-se apenas a abertura e o nível de saída, porque o extremo oposto pode ter ocorrido depois da saída. As saídas intrabar são conhecidas no replay no fechamento do candle; não se inventa um horário exato de execução dentro dele. A curva de equity e o drawdown também usam fechamentos, sem afirmar um drawdown intrabar exato.

O saldo evolui com o P&L líquido realizado. Limites de perda diária usam dia UTC e drawdown usa o maior patrimônio observado nos fechamentos. O simulador aceita uma exposição por vez e conta entradas efetivamente preenchidas, não apenas sinais.

## Aprendizado persistente

O schema SQLite atual é 3, com migração aditiva dos schemas 1/2. `simulated_execution_events` guarda preenchimentos, rejeições, saídas e censura; `market_intelligence` liga o EvidenceSet ao snapshot V3. O contexto original de tendência, evidências, confirmação e gatilho acompanha o resultado sem reclassificação posterior. O journal permanece append-only. Cada candle usa uma transação única para gravar suas observações, decisões e eventos relacionados; uma falha reverte esse conjunto e interrompe a execução.

O resultado gera uma nova `ExperienceRecord` ligada ao snapshot, à decisão e à hipótese original. O registro antigo não recebe retrospectivamente informação futura. A recuperação de memória continua limitada à própria execução e a timestamps estritamente anteriores à decisão atual; resultados só ficam disponíveis depois de conhecidos.

Conformidade e resultado financeiro são distintos. Uma perda seguindo todas as regras é `good_process_loss`; lucro com violação seria `poor_process_profit`. As classificações significam aderência à política simulada, não prova de que a estratégia é boa. Resultados censurados são falhas técnicas, não perdas financeiras supostas. Nenhuma classificação promove a estratégia ou altera risco/configuração.

## Avaliação 60/20/20

`--validate-temporal` divide os candles cronologicamente em desenvolvimento (60%), validação (20%) e holdout final (20%). Cada janela tem warmup, conta, exposição e memória independentes. Posições são encerradas na fronteira para impedir que o resultado de uma janela dependa dos preços da próxima.

O plano sela configuração, hashes dos dados e fronteiras antes de executar qualquer janela. A configuração é a mesma para desenvolvimento e validação; nenhum treinamento ou busca de parâmetros ocorre neste comando. O holdout é somente identificado e reservado por padrão, sem replay ou cálculo de desempenho.

O diretório `data/replays/validation-<id>/` contém `plan.json`, `summary.json`, `report.html` e os subdiretórios dos replays executados. O relatório compara as métricas por janela e aponta a janela final como não avaliada. Mesmo quando avaliada explicitamente, uma amostra pequena continua insuficiente para concluir rentabilidade; o piso de amostras no relatório é apenas um filtro mínimo, sem garantia estatística.
