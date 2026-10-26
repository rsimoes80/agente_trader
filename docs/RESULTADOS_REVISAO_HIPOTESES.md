# Validação do ciclo de crítica e revisão — 26/10/2026

## Conclusão desta etapa

O ciclo funciona como pesquisa automatizada, mas os filtros testados **não
demonstraram uma estratégia lucrativa**. Reduzir a perda total reduzindo o número
de operações não basta para aprovar uma alternativa. Nenhuma regra foi ativada.

## Fonte e reprodução

- Dataset congelado: `661f1b42-0b1d-4066-a145-85f8cd0334ae`.
- 1.421 candidatos, 74.520 candles M5 do MT5, cerca de 335 dias de histórico.
- Registros e candles verificados por hash no PostgreSQL. O replay recebe
  somente características e contexto anteriores à entrada; os antigos rótulos
  financeiros foram excluídos da entrada do experimento.
- Protocolo final V3: `11b13b41f4139aee28954f44945887880d60d11c80ae04f3144c8aaaf56a9c38`.
- Relatório: `agent_review_experiment`, chave
  `6d46ef1b110ed57beec1d74a3b6f7d3f9abb20112be72bc1fb5a56bf1ab3bc70`.
- Cópia local: `data/reports/hypothesis-review-6d46ef1b110e.json`.
- Comando: `python run_hypothesis_review_experiment.py --long-comparison`.

Os dados já orientaram outras pesquisas. A separação cronológica abaixo não é
validação prospectiva inédita. Modelos, carteira, custos e fonte foram congelados;
não houve envio de ordens, ajuste de pesos ou alteração da política demo.

## Política atual e universo de pesquisa

Na política atual, 1.414 candidatos foram bloqueados pelo regime e seis pela
confirmação de tendência. Houve uma operação, com −US$ 1,18. Isso não permite
avaliar o benefício econômico do novo ciclo.

O universo ampliado, exclusivamente de pesquisa, encerrou 657 operações, com
235 ganhos e −US$ 175,38 líquidos. Não houve exposição censurada nesse replay.
Esse total não representa operações executadas na conta do usuário.

O ciclo formulou quatro propostas em contextos distintos. Todas encerraram
com amostra futura insuficiente. A primeira, sobre candles de corpo fraco,
produziu estas carteiras nos 14 dias seguintes:

| Carteira | Encerradas | Líquido USD |
|---|---:|---:|
| Base | 16 | −1,95 |
| Filtro de corpo fraco | 15 | −2,31 |

O filtro não melhorou esse recorte. Outros testes tiveram carteiras com zero
operações: resultado zero sem entrar não comprova vantagem ou acerto.

## Comparação mais longa

Descoberta: início do catálogo em novembro/2025 até junho/2026. Checagem:
julho/2026 até 20/10/2026. Cada braço foi simulado como carteira completa,
com oportunidades, disponibilidade de posição e custos próprios. O teste longo
usa a mesma regra de encerramento de sessão conhecido para todos os braços;
seus totais não devem ser confundidos com o replay contínuo acima.

| Regra | Descoberta: operações / líquido USD | Checagem: operações / líquido USD |
|---|---:|---:|
| Base | 465 / −126,31 | 192 / −49,38 |
| Exigir ausência de contradições | 154 / −51,81 | 67 / −21,19 |
| Exigir confirmação Timestral | 199 / −62,81 | 79 / −10,34 |
| Evitar corpo fraco | 443 / −93,50 | 186 / −44,52 |
| Exigir previsão de 30 min maior que os custos estimados | 10 / −6,34 | 3 / −1,17 |

Nenhum filtro cumpriu lucro líquido positivo e PF ≥ 1,1 no desenvolvimento.
Portanto não houve selecionada para aprovação ou estresse confirmatório.
Na checagem, confirmação Timestral teve 43,04% de ganhos e PF 0,715: ainda perdeu.
Seu ganho bruto de US$ 7,07 foi inferior aos US$ 17,41 de custos. Na base, o
resultado bruto também era negativo (−US$ 7,03), antes de US$ 42,35 de custos.

O quarto filtro foi acrescentado após esse diagnóstico e registrado antes do
novo replay. Ele usa as premissas de custos existentes, sem escolher um limiar
que maximize o resultado. Só produziu dez e três operações nos dois períodos,
ambos negativos. Isso indica uma limitação da previsão mediana disponível;
não justifica reduzir os custos ou mínimos de amostra para aprovar o modelo.

## Correções de implementação

- Conferência do resultado contra o evento financeiro do simulador.
- Inclusão dos conflitos do contexto, além das contradições do candidato.
- Carteiras base e filtrada independentes, incluindo novas oportunidades
  liberadas por uma entrada evitada.
- Continuidade após uma pesquisa terminar: outra proposta exige dados novos;
  a mesma combinação de contexto e crítica não é repetida na mesma versão.
- Amostra insuficiente, dados censurados e falta de benefício não autorizam
  mudança de estratégia. Uma indicação favorável ainda exige confirmação.
- Resumo do painel não transmite checkpoints e listas de trades das carteiras.

## Verificações técnicas

66 casos de teste aprovados, incluindo a integração PostgreSQL habilitada
explicitamente em schemas de teste isolados; nenhum foi pulado na execução final.
Incluem fronteira temporal, ausência de dados, custos, consistência financeira,
idempotência, retomada de pesquisa, preservação dos preenchimentos e oportunidades
da carteira filtrada enquanto a base está ocupada. Python/JavaScript e diff
verificados. Uma gravação/recuperação real no PostgreSQL preservou exatamente
o checkpoint de aprendizado, sem modificar a sessão operacional.

## Trabalho restante para o objetivo de rentabilidade

Não há evidência para promover esses filtros. A próxima hipótese deve adicionar
informação capaz de distinguir movimentos grandes o suficiente para superar os
custos, e ser testada com carteira completa e período separado. A mera direção
positiva do Timestral não demonstrou essa capacidade. Os quatro filtros e os limites
de aprovação não foram ajustados até produzir um vencedor histórico.
