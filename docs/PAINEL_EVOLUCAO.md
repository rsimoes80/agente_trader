# Painel de evolução do aprendizado

Disponível na página inicial, em **Evolução do aprendizado**. Atualiza junto
com o estado do agente, sem comandos manuais para cada hipótese.

## Como ler

- **Atividade:** candles analisados desde a instalação deste acompanhamento e
  hipóteses técnicas identificadas pelo laboratório exploratório.
- **Alternativas simuladas:** operações encerradas, ganho médio positivo, perda
  média negativa, resultado líquido após custos e diferença para a base. Uma
  diferença positiva pode significar apenas uma perda menor; não comprova lucro.
- **Queda realizada:** maior queda acumulada dos resultados encerrados em USD,
  na janela retida. Não é drawdown da conta MT5 e não inclui posições abertas.
- **Motivos de espera:** uma decisão final por candle. Os motivos dos candidatos
  exploratórios aparecem separados, pois usam outra população e outro período.
- **Contextos:** regime, direção, sessão e faixa de volatilidade. Resultados de
  versões/fontes diferentes permanecem separados mesmo com rótulos semelhantes.
- **Próximas avaliações:** amostra no maior contexto durante descoberta; após
  formular uma proposta, amostra futura, fim dos 14 dias e avaliação após o dia
  adicional de liquidação. A data não dispensa o mínimo de amostras nem autoriza
  promoção. Sem proposta, não se inventa uma previsão de conclusão.

## Escopo dos números

As variantes usam os resultados retidos pelo aprendizado existente: últimos
90 dias, até 2.000 resultados no conjunto. A pesquisa exploratória usa até 1.000
revisões válidas retidas, reiniciadas após lacunas. Não é uma reconstrução de todo
o histórico da conta. Valores médios e queda sem amostra aparecem como ausentes.
A comparação usa carteiras paralelas, com quantidades de entradas possivelmente
diferentes; é descritiva, não uma estimativa causal ou teste pareado.

Operações reais da conta demo continuam na seção **Conta e resultados da sessão**.
As tabelas do painel são simulações e não se somam aos resultados do MT5.

## Saúde da coleta

A faixa de status distingue serviço Windows sem comunicação, preparação,
pausa solicitada, mercado semanal fechado, fonte inválida e análise recente.
Com o mercado aberto, mais de 15 minutos de negociação sem avanço do último
candle analisado gera alerta. O horário é o fechamento do candle M5; finais de
semana são descontados pelo calendário existente. O alerta não altera limites
de risco, estratégia, experimento ou estado de operação.

Falhas de previsão e simulações censuradas aparecem como ocorrências acumuladas,
não como afirmação de que o serviço está falhando neste instante. Os alertas são
visuais na plataforma; não enviam mensagens externas. A faixa não substitui as
verificações de cotação recente do executor.

## Implementação

`learning_evolution.py` calcula métricas sem modificar o aprendizado. A única
coleta nova é telemetria de decisões, idempotente por candle, no checkpoint
existente do PostgreSQL. Não há migração de tabelas, dependência adicional,
retreino, mudança de critérios ou reinício das amostras dos experimentos.
