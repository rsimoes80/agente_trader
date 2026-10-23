# Investigação separada de gatilho e saída

Experimento offline de 23/10/2026, no Agente Trader - IA. Não altera o agente
demo nem envia ordens. Execução:

```powershell
.venv/Scripts/python.exe run_trigger_exit_experiment.py
```

## Fonte e controle

Reutiliza os 107 sinais congelados do
[teste de tendência com correção](EXPERIMENTO_TENDENCIA_COM_CORRECAO.md),
cuja carteira encerrou 25 operações e perdeu 6,16 USD. O runner confere a
integridade do relatório e dos candles e exige reproduzir exatamente o
controle original antes de testar qualquer alternativa.

Não regenera a percepção nem procura sinais novos. Filtros de qualidade podem
somente excluir sinais desse conjunto; não adiam a entrada nem mudam seu preço.
As características são calculadas com os candles disponíveis no fechamento do
gatilho, sem consultar preços futuros.

## Alternativas fixadas antes dos resultados

| Grupo | Alternativa | O que muda |
|---|---|---|
| Referência | Gatilho original, 60 minutos | Nada |
| Gatilho | Corpo de pelo menos 0,5 ATR | Somente esse filtro |
| Gatilho | Fechamento nos 25% finais do candle | Somente esse filtro |
| Gatilho | Fechamento rompendo os três candles anteriores | Somente esse filtro |
| Saída | Duração máxima de 30 minutos | Somente 12 para 6 candles M5 |
| Saída | Duração máxima de 120 minutos | Somente 12 para 24 candles M5 |

Na venda, a posição do fechamento é medida a partir da máxima, em direção à
mínima. Na compra, a partir da mínima, em direção à máxima. A ATR de 14 barras
repete a conta do setup original. Rompimento significa fechamento além de
todas as três máximas ou mínimas anteriores, conforme a direção permitida.

Os três filtros não são combinados entre si. Nenhum filtro é combinado com
mudança de saída. São definições de engenharia para esta investigação, não
limiares otimizados depois de observar os resultados.

## Condições comuns

- H4/H1 confirmados e alinhados e somente entradas na direção permitida.
- Mesmo lote 0,01, ponto de entrada, stop, alvo 2,5R e uma exposição por vez.
- Mesmos limites de risco, mínimo retorno/risco líquido 2 e cinco entradas/dia.
- Mesmo spread observado, slippage de mercado 0,2 pip e comissão de
  35 USD/milhão por lado.
- Contas independentes nos períodos originais; exclusão das últimas duas
  horas para novos sinais em todos os braços, incluindo o controle, por causa
  da maior duração testada. O controle original com exclusão de uma hora é
  reproduzido separadamente como verificação.
- Falhas inesperadas durante exposição censuram o resultado.
- Sem modelo de swap. Duração é em candles observados: possíveis exposições
  que atravessam fechamento de mercado são contabilizadas e sinalizadas.

Há também uma comparação auxiliar das saídas partindo de cada operação
efetivamente preenchida na referência, em contas individuais independentes.
Ela ajuda a separar o efeito da duração do efeito de liberar a carteira mais
cedo para outro sinal. Não é uma carteira executável e seus resultados não
devem ser somados ao resultado do portfólio.

## Interpretação

Os 335 dias e suas divisões já foram pesquisados. Os números são retrospectivos
e exploratórios, não uma nova validação fora da amostra. Há seis comparações;
escolher a maior delas não demonstra vantagem estatística.

O script grava o protocolo em `agent_trigger_exit_protocol` antes do cálculo e
o relatório completo em `agent_trigger_exit_experiment`, no PostgreSQL. O JSON
local fica em `data/reports/trigger-exit-<hash>.json`, fora do Git.

Nenhuma alternativa é promovida automaticamente por este experimento, mesmo
que uma delas termine com lucro. Os limites de risco não são reduzidos para
aprovar sinais anteriormente vetados.

## Resultados concluídos

Fonte de 74.520 candles M5, com 335 dias de análise e aquecimento anterior.
Todos os números abaixo são da hipótese experimental com correção, não da
política estrita que permanece ativa na conta demo.

| Alternativa isolada | Sinais | Operações | Ganhos / perdas | Acerto | Líquido USD | Média/operação USD |
|---|---:|---:|---:|---:|---:|---:|
| Referência: gatilho original, 60 min | 107 | 25 | 8 / 17 | 32% | -6,16 | -0,25 |
| Corpo >= 0,5 ATR | 97 | 25 | 8 / 17 | 32% | -6,16 | -0,25 |
| Fechamento nos 25% finais | 88 | 21 | 4 / 17 | 19,0% | -11,17 | -0,53 |
| Rompimento dos três anteriores | 46 | 16 | 6 / 10 | 37,5% | -5,36 | -0,33 |
| Duração máxima 30 min | 107 | 26 | 9 / 17 | 34,6% | -4,99 | -0,19 |
| Duração máxima 120 min | 107 | 24 | 4 / 20 | 16,7% | -9,15 | -0,38 |

### 1. Qualidade do gatilho

- **Corpo forte:** excluiu dez sinais, mas nenhuma das 25 operações efetivamente
  preenchidas. Não separou operações vencedoras e perdedoras neste conjunto.
- **Fechamento no extremo:** piorou resultado e acerto. Alterou a composição da
  carteira, não apenas o número de sinais.
- **Rompimento de três candles:** elevou o acerto observado para 37,5%, mas
  continuou perdendo dinheiro e piorou o resultado médio por operação. Uma
  redução da perda total acompanhada de menos operações não comprova melhor
  expectativa. Seu fator de lucro foi 0,57, contra 0,66 da referência.

### 2. Política de saída

- **30 minutos:** reduziu a perda total, mas permaneceu negativa. O drawdown
  máximo realizado foi 0,1357%, contra 0,1291% da referência; a menor perda
  final não significou melhora em todas as medidas de risco.
- **120 minutos:** piorou resultado, acerto e drawdown realizado (0,1756%).
- Das 16 operações encerradas por stop na referência, **12 chegaram ao stop
  em até seis candles M5**, com mediana de 4,5 candles. Apenas estender o prazo
  não evita um stop que já foi atingido.

Na comparação auxiliar das mesmas 25 entradas, cada uma simulada isoladamente,
30 minutos produziram -3,21 USD, contra -6,16 USD em 60 minutos; sete melhoraram,
quatro pioraram e 14 ficaram iguais. Em 120 minutos, o líquido foi -6,41 USD;
duas melhoraram, quatro pioraram e 19 ficaram iguais. As referências individuais
reproduziram exatamente os resultados das mesmas operações da carteira original.

Esses totais auxiliares **não são resultados de portfólio**: ao sair antes ou
depois, a carteira pode aceitar ou perder outros sinais e atingir o limite
diário em momentos diferentes. Por isso, a carteira de 30 minutos teve 26
operações, enquanto a de 120 minutos teve 24.

### 3. Estabilidade temporal — líquido USD

| Alternativa | Desenvolvimento | Validação | Final já conhecida |
|---|---:|---:|---:|
| Referência | +1,31 | -3,54 | -3,93 |
| Corpo >= 0,5 ATR | +1,31 | -3,54 | -3,93 |
| Fechamento nos 25% finais | -3,73 | -3,51 | -3,93 |
| Rompimento de três candles | -3,96 | +0,88 | -2,28 |
| 30 minutos | +1,21 | -3,74 | -2,46 |
| 120 minutos | -2,06 | -5,06 | -2,03 |

O +0,88 USD do rompimento de três candles na validação veio de **uma única
operação**. Não é uma evidência robusta de melhora. Nenhuma alternativa ficou
lucrativa no total ou na janela final.

### 4. Limitação importante: somente vendas executadas

Os 107 sinais continham 49 compras e 58 vendas. Na referência, as 49 compras
foram vetadas por retorno/risco líquido insuficiente. Das vendas, 22 tiveram o
mesmo veto e cinco esbarraram no limite diário. As 25 operações preenchidas
foram vendas. Portanto, estes resultados não medem a qualidade de compras
efetivamente executadas e não demonstram que compras sejam piores.

O setup deriva stop/alvo do candle bid; compras entram no ask acrescido do
slippage, e o risco recalcula a viabilidade no preço executável. A diferença
entre o plano nominal e o preço de execução é relevante para essa seleção.
Isso não autoriza reduzir o retorno/risco mínimo. Uma hipótese de objetivo
calculado a partir da cotação executável seria outro teste, com protocolo
próprio; não foi misturada aos seis braços desta investigação.

## Conclusão e decisão

**Nenhuma dessas alterações demonstrou vantagem suficiente para ativação.**
Manter o agente demo na regra atual. Não combinar retrospectivamente os
melhores números de braços diferentes para declarar uma estratégia vencedora.

A investigação desloca a prioridade para validar o contexto da entrada:
confirmar se existe impulso anterior e uma correção efetiva, em vez de apenas
um pequeno recuo M5 dentro de uma direção estrutural. Os filtros de candle
testados e o aumento da duração não resolveram as perdas. Essa explicação de
contexto ainda é uma hipótese, não uma conclusão causal demonstrada.

### Registro e verificações

- Protocolo: `d90a85f81ecad06d1704a46cb80c2a14d984ce05fa3533dbe79d9d2fd4e81eb1`.
- Registrado antes dos resultados em 23/10/2026, 12:44:24 UTC (09:44:24 de Brasília).
- Relatório PostgreSQL: `ee9ca0a18a6e0ae9bda966109f6066295f7b0c88368013f3860f4f6e728b6b4b`.
- Arquivo local: `data/reports/trigger-exit-ee9ca0a18a6e.json`.
- Controle anterior reproduzido exatamente; exclusão comum de duas horas não
  mudou seu resultado nesta fonte.
- Referência completa e referências individuais reproduzidas de novo; auditoria
  de vetos por direção registrada em `agent_trigger_exit_check`.
- Nenhuma exposição censurada, pendente ou acima da duração nominal nos seis
  portfólios. Os efeitos de swap não foram avaliados.
- Testes cobrem isolamento das variáveis, custos, durações, integridade da
  direção, exclusão de informação futura e reprodução do portfólio anterior.
- 18 testes direcionados de gatilho/saída, correção, tendência e expiração
  passaram. Hash da implementação e integridade do registro PostgreSQL conferidos.
- Código operacional, modelos, configuração Timestral e regras de risco intactos.
