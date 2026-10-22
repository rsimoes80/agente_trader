# Entradas somente a favor da tendência

## Regra operacional

Política `trend-only-h4-h1-confirmed-v1`, aplicada a todas as hipóteses,
inclusive seleção exploratória, Timestral e simulação ao vivo:

| Contexto | Nova entrada |
|---|---|
| H4 e H1 com alta confirmada, regime TREND | Somente compra |
| H4 e H1 com baixa confirmada, regime TREND | Somente venda |
| H4 e H1 divergentes | Aguardar |
| Tendência potencial, enfraquecida, ausente ou indefinida | Aguardar |
| RANGE, TRANSITION ou UNKNOWN | Aguardar |

O gatilho continua em M5. Correções menores não são autorização para operar
contra H4/H1. D1 permanece contexto adicional; não substitui essa hierarquia.
Reversões só permitem a direção nova após confirmação e alinhamento dos dois
períodos. O código usa candles fechados e o classificador estrutural existente;
não introduz uma média móvel como substituto da tendência confirmada.

A regra é verificada na proposta, seleção de hipótese, abertura da conta e
gateway demo antes do SDK. Encerramentos e reconciliação continuam permitidos:
uma venda para fechar uma compra não é uma nova entrada vendida.

## Memória e pesquisa

O identificador da política é gravado na decisão e no journal de novas entradas.
O aprendizado contextual da política nova tem chaves próprias. Resultados das
regras anteriores continuam preservados, mas não pontuam a seleção atual nem
são somados aos resultados das hipóteses da regra nova. O saldo e o histórico
financeiro completo da conta permanecem iguais.

Na memória histórica inicial só entram amostras de desenvolvimento cujo snapshot
confirme o mesmo alinhamento. Isso pode reduzir o número de experiências válidas.
O replay contrafactual offline permanece disponível e identificado; seus padrões
sem tendência confirmada não autorizam ordens. Não houve ajuste dos pesos Timestral.

## Referências consultadas

- Pring, *Análise Técnica Explicada*, PDF local, páginas 16–17: identificar a
  tendência e distinguir horizontes antes de interpretar um sinal menor.
- Lefèvre/Livermore, *Reminiscências de um Especulador Financeiro*, PDF local,
  páginas 48 e 67: observar o movimento geral, esperar e distinguir estar certo
  na direção de acertar o momento da entrada.
- Brooks, *Operando Price Action: Tendências*, PDF local, página 135, impressa 95:
  a direção do trade em relação à tendência define se a operação é a favor ou
  contra; uma barra isolada pode sustentar interpretações opostas.
- [Brooks, Countertrend trading](https://www.brookstradingcourse.com/ask-al/countertrend-trading/):
  pressão compradora persistente é motivo para cautela com vendas contra a alta.
- [Brooks, trecho publicado pela Wiley, páginas 1–2](https://catalogimages.wiley.com/images/db/pdf/9781118066614.excerpt.pdf):
  uma tentativa de reversão pode falhar e tornar-se uma correção de continuidade.

Os autores também discutem operações contra a tendência em contextos específicos.
A proibição absoluta aqui é um requisito do projeto. H4/H1 e os critérios de
confirmação são escolhas de engenharia; não são uma fórmula atribuída aos livros
nem garantia de lucro. Seguir a tendência não elimina perdas.
