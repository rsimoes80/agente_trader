# Hipótese: tendência com correção

## Pergunta

O filtro de regime impede entradas de retomada válidas quando H4 e H1 ainda
estão confirmados na mesma direção, mas a geometria recente não é TREND?

Experimento offline solicitado em 23/10/2026. Nenhuma ordem é enviada e nenhuma
regra do agente demo é alterada por este comando:

```powershell
.venv/Scripts/python.exe run_correction_experiment.py
```

## Comparação fixada antes dos resultados

1. **Atual:** regime TREND, H4/H1 confirmados e alinhados, gatilho de pullback M5.
2. **Atual + correção protegida:** conserva as entradas anteriores e acrescenta
   retomadas em UNKNOWN ou TRANSITION, com todas as condições abaixo.

Entradas adicionais exigem:

- H4 e H1 confirmados e alinhados; venda apenas em baixa e compra apenas em alta.
- Histórico válido e nenhum indício invalidante registrado na percepção.
- Últimos três candles M5 anteriores ao gatilho com deslocamento líquido contra
  H1 e pelo menos um corpo de candle na direção da correção.
- Quatro fechamentos M5 recentes preservando o último fundo H1 confirmado na
  alta ou o último topo H1 confirmado na baixa. O pivô precisa estar confirmado
  antes da decisão; não se utiliza a confirmação futura de um swing.
- Candle M5 de retomada fechando além da máxima/mínima anterior, do lado correto
  da EMA21 e com corpo a favor de H1. O setup de pullback original também precisa
  passar, incluindo spread, contexto diário e stop.
- Regime RANGE continua bloqueado para entradas adicionais. Não basta que a
  direção estrutural esteja apontando para algum lado.

O classificador experimental distingue impulso, correção, retomada, contexto
não confirmado e possível reversão. Conflito H4/H1 ou perda do nível protegido
impedem entradas adicionais. Uma correção sem gatilho significa esperar.

As condições numéricas são hipóteses de engenharia. Não são fórmulas atribuídas
aos livros e não foram ajustadas para maximizar o resultado deste teste.

## Método

- Seleção anterior aos resultados: maior dataset histórico congelado compatível
  com a estratégia. Candles e registros conferidos por hash.
- Regeneração sequencial dos candidatos a partir dos candles M5, usando a
  percepção atual com a correção de expiração. O catálogo antigo de 1.421
  candidatos não é a única fonte de sinais deste experimento.
- Só candles fechados e agregações causais H4/H1/M15/D1.
- Lote do dataset, saldo simulado inicial USD 10.000, posição única, limite de
  cinco entradas por dia, stop e alvo 2,5R originais, duração máxima de 12 M5.
- Spread observado, slippage de mercado de 0,2 pip e comissão de USD 35 por
  milhão por lado, conforme simulador existente. Execução na próxima abertura.
- Contas independentes nos períodos originais de desenvolvimento, validação e
  janela final. Sem novas entradas nos últimos 60 minutos de cada período.
- Falhas inesperadas de candles durante exposição censuram a simulação;
  resultado desconhecido não é convertido em ganho ou perda.
- Otimização de cálculo de níveis apenas no replay: cache de históricos
  imutáveis, atualização da expiração e seleção dos mesmos níveis antes de
  serializar. A implementação operacional continua intacta.

O protocolo é persistido em `agent_correction_protocol` antes do cálculo. O
relatório completo, candidatos e resultados ficam em
`agent_correction_experiment` no PostgreSQL e em
`data/reports/correction-<hash>.json`, fora do Git.

## Limites

Esses preços já foram pesquisados. As divisões temporais ajudam a identificar
instabilidade, mas não são um novo teste independente fora da amostra.

O experimento compara a elegibilidade técnica do pullback; não reproduz a
seleção adaptativa completa do agente, não retreina pesos Timestral e não mede
o resultado de ordens reais. Mais sinais não equivalem a mais operações, porque
posição existente e risco continuam limitando a execução.

Um resultado retrospectivo favorável é motivo para validação futura, não para
promover automaticamente a alternativa. As regras em produção permanecem iguais.
