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

## Resultado concluído em 23/10/2026

Fonte: 74.520 candles M5, 335 dias de análise e 30 dias de aquecimento.
Período de análise: 19/11/2025 a 20/10/2026, em UTC. Lote 0,01.

| Métrica — período completo | Atual | Atual + correção protegida |
|---|---:|---:|
| Sinais elegíveis | 1 | 107 |
| Operações encerradas | 1 | 25 |
| Ganhos / perdas líquidos | 0 / 1 | 8 / 17 |
| Acerto observado | 0% | 32% |
| Resultado líquido USD | -1,18 | -6,16 |
| Resultado médio por operação USD | -1,18 | -0,25 |
| Fator de lucro | 0 | 0,66 |
| Drawdown máximo realizado | 0,0118% | 0,1291% |
| Resultados censurados / posição pendente | 0 / não | 0 / não |

Os 107 sinais incluem o sinal da regra atual e 106 adicionais. Na carteira
alternativa, seis sinais encontraram exposição existente e 76 foram vetados
pelo risco; os 25 restantes viraram operações encerradas.

Uma reprodução exata da carteira confirmou os vetos: 71 por relação
retorno/risco líquida insuficiente e cinco pelo limite diário de operações.
As saídas foram 16 stops, seis por duração máxima e três por alvo. Essa
verificação está registrada como `agent_correction_replay_check` no PostgreSQL.

O resultado antes de custos da alternativa foi -0,66 USD. Spread de 2,81 USD,
slippage de 0,94 USD e comissão de 1,75 USD levaram ao líquido de -6,16 USD.
Não é uma estratégia lucrativa que se tornou inviável somente pelas taxas:
o resultado bruto também foi negativo.

### Estabilidade temporal da alternativa

| Período original | Operações | Ganhos / perdas | Acerto | Líquido USD |
|---|---:|---:|---:|---:|
| Desenvolvimento | 14 | 6 / 8 | 42,9% | +1,31 |
| Validação | 6 | 1 / 5 | 16,7% | -3,54 |
| Janela final já conhecida | 5 | 1 / 4 | 20% | -3,93 |

A regra atual teve uma operação no desenvolvimento e nenhuma nos outros dois
períodos; ausência de operações não significa acerto de 0%. Cada período tem
conta independente e exclusão de sinais na última hora, conforme protocolo.

### Conclusão

O bloqueio de regime é, de fato, um limitador forte da quantidade de entradas.
A alternativa examinada aumentou as operações, mas não demonstrou vantagem
financeira: perdeu no total e nas duas janelas posteriores ao desenvolvimento.

O controle tem apenas uma operação. Portanto, 32% contra 0% não comprova uma
melhora estatística de assertividade. O intervalo Wilson descritivo da
alternativa é aproximadamente 17,2%–51,6%, sem pressupor independência temporal.

**Não promover esta versão para o agente demo.** O próximo estudo deve separar
qualidade do gatilho de retomada e política de saída/duração, alterando uma
variável por vez, sem afrouxar o risco para fazer sinais rejeitados passarem.
Nenhuma dessas hipóteses seguintes foi calibrada neste experimento.

### Rastreabilidade e verificações

- Código de reprodução: commit `d1934fe`.
- Dataset de origem: `661f1b42-0b1d-4066-a145-85f8cd0334ae`.
- Protocolo concluído: `c7e3c7b38c8427f1a4ee3b31b4b1ab4b2983c1c9972c2e78ce4f27487c9a8cef`.
- Registro anterior ao cálculo: 23/10/2026, 11:49:32 UTC (08:49:32 de Brasília).
- Relatório PostgreSQL: `6ba3f9946d64314f98f0d1181967b64e9a9ec2d675fe1967f37d78152caf392f`.
- Arquivo local: `data/reports/correction-6ba3f9946d64.json`.
- Hash dos três arquivos da implementação confere com o protocolo registrado.
- 14 testes de correção, tendência e expiração passaram, incluindo direção,
  pivôs futuros, preservação da estrutura, equivalência dos níveis e dos custos
  de sinais comuns, censura por falhas de dados e regra de produção intacta.
- Duas execuções de preparação foram interrompidas antes de resultados para
  reduzir o custo do replay. Não houve seleção de parâmetros por desempenho.

O agente permaneceu na mesma sessão e geração, em execução. A política de
entrada, o hash do regime e a configuração Timestral foram preservados.
