# Flexibilização para daytrade — 28/10/2026

A política configurada nos workers desta VM é `daytrade-h1-confirmed-v1`.
A direção é definida pela tendência H1 confirmada: compras somente com
`BULL_CONFIRMED` e vendas somente com `BEAR_CONFIRMED`. Potenciais tendências,
estados enfraquecidos, direção indefinida e operações contrárias continuam
bloqueados. H4 e D1 passam a ser contexto da decisão, e não a definição da
direção do daytrade. Assim, H4 contrário pode coexistir com um trade a favor
do H1: essa distinção de horizonte é explícita, não uma confirmação macro.

## O que mudou

- O classificador H1 não precisa também declarar regime `TREND` quando a
  estrutura de tendência H1 já está confirmada. RANGE, TRANSITION e UNKNOWN
  continuam registrados como features, sem vetar isoladamente a entrada.
- H4 não precisa confirmar a mesma direção; seus estados e divergências
  permanecem disponíveis para análise e aprendizado.
- O gatilho atual de pullback foi mantido: correção anterior e fechamento de
  candle na direção H1, além do extremo anterior e da EMA. Nenhuma entrada
  é autorizada apenas porque o modelo sugere uma direção.
- Dados válidos, calendário/sessões, spread máximo, stop, custos, limites de
  risco, limite diário e reconciliação não foram relaxados. Não se aumentou lote.
- A memória de seleção da política antiga fica preservada em outro namespace;
  nova versão de estratégia e aprendizado impede tratá-la como validação atual.

O contexto diário continua sendo coletado para features do modelo; não foi
removido seu preparo porque estava disponível em todos os candles avaliados e
não era a causa dos bloqueios. O horizonte de posição segue curto: o simulador
usa até 12 candles M5, além das regras de encerramento de sessão. Isso não
converte o OHLC histórico em uma garantia de tempo ou preço de execução real.

## Comparação pré-declarada

Comando usado, sem alterar a reserva final do plano original:

```bash
.venv/bin/python run_operational_audit.py \
  --plan data/replays/validation-b40c0837-50cc-4af5-9d28-27a34fac865f/plan.json \
  --warmup data/provisioning/verification/warmup-60days.json \
  --compare-daytrade
```

As três hipóteses foram declaradas antes de observar os novos resultados:
original; H1 confirmado com gatilho original; H1 confirmado com continuação
mais flexível. O último gatilho admite fechamento além do fechamento anterior,
sem exigir romper sua máxima/mínima, mas ainda exige correção, EMA, candle na
direção da tendência e os demais controles. Não houve busca de parâmetros ou
seleção automática de vencedor pelo resultado financeiro.

Fonte: mesmas partições M5 congeladas e verificadas por hash — 3.798 candles
para desenvolvimento e 1.266 para validação — com contexto anterior dos 60
dias preparados. A reserva iniciada em 22/10/2026 03:05 UTC não foi avaliada.
São dados já observados em avaliações anteriores: não constituem um novo teste
independente da decisão de alterar a política.

Custos de pesquisa: spread histórico, slippage de 0,2 pip por execução e
comissão de US$ 35 por milhão por lado. Estresse: spread multiplicado por 1,5
e slippage de 0,4 pip. A comissão não é uma tarifa confirmada da conta demo.
As carteiras usam conta sintética de US$ 10.000 e 1.000 unidades (0,01 lote
padrão), independentes em cada partição. Entrada na abertura seguinte ao sinal;
nenhum trade é aberto para aproveitar o resultado futuro. A última hora de
cada janela é excluída de novas entradas para respeitar a fronteira temporal.

| Política | Propostas desenvolvimento / validação | Operações normais desenvolvimento / validação | P&L normal desenvolvimento / validação |
| --- | --- | --- | --- |
| Original H4+H1+regime | 0 / 0 | 0 / 0 | US$ 0 / US$ 0 |
| H1 confirmado, pullback original | 116 / 31 | 26 / 6 | -US$ 2,30 / -US$ 2,51 |
| H1 confirmado, continuação flexível | 181 / 48 | 27 / 6 | -US$ 2,50 / -US$ 2,51 |

| Política | Operações sob estresse desenvolvimento / validação | P&L sob estresse desenvolvimento / validação |
| --- | --- | --- |
| H1 confirmado, pullback original | 15 / 4 | -US$ 2,59 / -US$ 2,73 |
| H1 confirmado, continuação flexível | 17 / 4 | -US$ 3,36 / -US$ 2,73 |

Propostas não equivalem a ordens preenchidas: custos, relação retorno/risco,
limite diário e exposição simultânea continuam restringindo a execução.
Não houve posição censurada ou pendente em nenhuma das carteiras comparadas.

## Leitura do resultado e estado do ambiente

A retirada dos vetos de regime/H4 produziu 147 propostas e 32 operações
hipotéticas onde antes não havia nenhuma. Soltar também o gatilho produziu
mais propostas, mas somente uma operação adicional no desenvolvimento e
nenhuma adicional na validação. Por isso, o gatilho mais flexível permanece
uma hipótese offline, enquanto a configuração dos workers mantém o gatilho
original e usa a direção H1 confirmada.

A mudança atende ao objetivo de obter mais oportunidades de pesquisa; ela
não demonstrou rentabilidade. Ambas as versões tiveram P&L negativo e a
validação tem somente seis operações normais por versão. Não se ajustou
risco para compensar perdas. A avaliação continua limitada às propostas e
suas carteiras hipotéticas, antes da previsão e seleção pelo aprendizado:
não é validação integral do agente nem do modelo Timestral.

Artefatos privados e código executado:
`data/reports/operational-audit-e8904c55-94b7-4149-9161-3f6327ef6f1f/`.
O protocolo e resultados agregados estão no PostgreSQL. Os artefatos incluem
os sources usados na comparação; atualizações posteriores de configuração
não reescrevem esses resultados.

A sessão operacional continua `STOPPED`, sem exposição e sem ordens enviadas
nesta alteração. A nova política está configurada para a próxima sessão;
a alteração não iniciou aprendizado ao vivo nem negociação automaticamente.
A coleta do histórico permanece ativa. Passaram 92 testes com a política H1
configurada e 36 testes de compatibilidade da política estrita e experimentos.
