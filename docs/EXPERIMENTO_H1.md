# Experimento H1 versus H4+H1 — 22/10/2026

## Hipótese e protocolo

Retirar somente a exigência de confirmação/alinhamento de H4 aumenta entradas
e melhora a taxa de operações com lucro líquido?

Teste offline, sem mudar o agente demo. Ambos exigem regime TREND e tendência
H1 confirmada com a mesma direção da entrada. M5, gatilho, lote 0,01, sessões,
spread observado, comissão, slippage, posição única, limite diário de cinco
entradas e duração máxima de 12 candles continuam iguais. Saldo simulado
inicial USD 10.000; não é o saldo da conta demo.

Selecionado antes de calcular resultados o maior catálogo congelado compatível:
335 dias de análise e 30 de aquecimento, 74.520 candles M5, 1.421 candidatos
históricos. Período analisado: 19/11/2025 a 20/10/2026, horários UTC.
Fonte: dados MT5 persistidos no PostgreSQL. A integridade dos registros e o
hash dos candles foram verificados. Não houve ajuste de parâmetros após o resultado.

## Resultado do replay do catálogo

| Métrica | H4+H1 | Somente H1 |
|---|---:|---:|
| Sinais elegíveis | 1 | 2 |
| Operações encerradas | 1 | 2 |
| Ganhos / perdas | 0 / 1 | 0 / 2 |
| Acerto líquido | 0% | 0% |
| Resultado líquido USD | -1,18 | -2,21 |
| Drawdown realizado máximo | 0,0118% | 0,0221% |

As três operações contadas nas duas colunas não são independentes: a operação
da regra H4+H1 também pertence ao conjunto H1. Não há posição pendente ao fim
dos replays. Na subdivisão temporal: desenvolvimento 1 operação em cada regra;
validação nenhuma; janela final já conhecida 0 em H4+H1 e 1 em H1.

**Conclusão limitada:** H1 liberou uma entrada adicional neste catálogo. Não
houve melhora de acerto observada, e a amostra é insuficiente para concluir
qual regra terá melhor desempenho futuro. Zero operações significa taxa
indefinida, não 0% de acerto.

## Por que tão poucas entradas?

Entre os candidatos catalogados, somente sete tinham regime TREND. Os demais:
423 RANGE, 632 TRANSITION e 359 UNKNOWN. Havia 478 candidatos alinhados a H1
confirmado quando se desconsiderava o regime, mas eles **não são 478 operações
autorizadas**: o bloqueio de regime continua comum às duas regras.

Isso identifica a classificação de regime como um ponto de investigação.
Não demonstra erro do classificador, nem autoriza retirar esse bloqueio para
melhorar retrospectivamente os números. Uma mudança no regime seria outra
hipótese e precisaria de protocolo próprio.

## Limites e rastreabilidade

- Replay retrospectivo de candidatos previamente rotulados e encerrados em
  simulações individuais; não abrange todo sinal que poderia surgir no mercado.
- Não reproduz a seleção adaptativa completa das hipóteses do robô nem retreina
  Timestral. É uma comparação isolada da elegibilidade de tendência.
- Janelas históricas já vistas não são um novo teste independente fora da amostra.
- Custos são os do simulador existente; resultados não são negócios executados
  pela corretora. Drawdown é calculado pela curva de patrimônio realizado.
- Intervalos Wilson são apenas descritivos; não se presume independência temporal.

Comando: `python run_trend_experiment.py`.

Registro PostgreSQL: `project_records`, tipo `agent_trend_experiment`, chave
`04b5875adb84d9818122347b0050925caf117dd53ec9703de35b57bfb31c2251`.
Catálogo: `661f1b42-0b1d-4066-a145-85f8cd0334ae`.
O relatório completo contém trades, custos, partições e identificação dos dados.

A política ativa permanece `trend-only-h4-h1-confirmed-v1`.
