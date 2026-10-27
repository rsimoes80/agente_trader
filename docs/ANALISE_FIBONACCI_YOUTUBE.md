# Fibonacci: avaliação para o Agente Trader - IA

Data: 27/10/2026. Estado: proposta de pesquisa; nenhuma alteração na execução.

## Fonte e alcance da análise

Referência indicada em `Aprendizado/youtube.txt`: [MASTER Fibonacci Trading in 85 Minutes (Complete Strategy Course)](https://www.youtube.com/watch?v=ryq0FBCyOLM), canal Mind Math Money, duração informada pelo YouTube de 84 minutos e 58 segundos.

Foi possível consultar a descrição e o índice de capítulos oficiais. As tentativas de obter legendas retornaram conteúdo vazio ou erro de pré-condição. Não foi possível conferir integralmente a fala, os exemplos visuais ou todas as regras da estratégia. Esta avaliação não representa uma revisão completa do vídeo. Limites exatos das três zonas de entrada não foram confirmados e não são atribuídos ao autor neste documento.

## O que a fonte permite identificar

O programa aborda ancoragem pelas máximas e mínimas dos pavios, zonas de retração, confluência com níveis e indicadores, extensões para alvos e alternativas de stop. Também inclui capítulos sobre extremos ainda não concluídos, redesenho constante das marcações e entradas sem gatilho. São assuntos compatíveis com a leitura de correção e retomada já presente no projeto. O índice não demonstra a rentabilidade dessas regras em EURUSD ou XAUUSD.

Pontos de consulta: [ancoragem, 20:09](https://www.youtube.com/watch?v=ryq0FBCyOLM&t=1209s), [confluência, 43:53](https://www.youtube.com/watch?v=ryq0FBCyOLM&t=2633s), [erros, 1:07:40](https://www.youtube.com/watch?v=ryq0FBCyOLM&t=4060s), [estratégia, 1:11:17](https://www.youtube.com/watch?v=ryq0FBCyOLM&t=4277s).

## Comparação com o código

| Elemento | Situação verificada | Contribuição possível |
| --- | --- | --- |
| Direção e contexto | `entry_trend.py` exige tendência confirmada e alinhada em H4/H1 na política examinada. | Não duplicar esse bloqueio. |
| Correção e retomada | `agent_strategy.py::propose_pullback` combina EMA21, correção e rompimento confirmado por fechamento. | Descrever a profundidade da correção em relação ao impulso. |
| Pesquisa de retração | `context_experiment.py` já compara uma correção positiva de até 50% após impulso mínimo de 1 ATR, com definição fixa de barras. | Comparar ancoragem estrutural com essa definição existente. Não apresentar retração como conceito inteiramente novo. |
| Extremos estruturais | `structure.py::Swing` contém `confirmed_at`, além da data do extremo. | Disponibilizar uma âncora somente quando sua confirmação já era conhecida. |
| Stops e alvos | A função de pullback examinada usa invalidação local com margem de ATR e alvo de 2,5R. | Pesquisar saídas estruturais ou por extensão em experimento separado. |

Não foi identificado um mecanismo dedicado de Fibonacci na função de entrada examinada. Menções em documentação antiga não comprovam implementação no caminho atual de execução. O alvo de 2,5R descrito acima pertence a essa função; não é uma afirmação sobre todas as estratégias de pesquisa do repositório.

## Recomendação

Faz sentido pesquisar Fibonacci como descrição objetiva do contexto e como alternativa de saída. Ainda não há evidência para torná-lo requisito obrigatório das entradas. Acrescentar uma condição obrigatória pode apenas reduzir oportunidades, um problema que o projeto já vem investigando.

Primeiro registrar, sem bloquear operações, a profundidade da correção, as âncoras usadas, o instante em que ficaram disponíveis e a distância dos níveis em unidades de ATR. O registro descritivo, por si só, não ajusta pesos do Timestral nem produz aprendizado validado.

### Definições necessárias antes de testar

- Escolher impulsos com critérios determinísticos e apenas informações disponíveis no instante da decisão. Um pivô confirmado posteriormente não pode aparecer antecipadamente no backtest.
- Fixar as âncoras de cada hipótese. Novos extremos podem invalidar ou originar uma nova hipótese conforme regra previamente definida; não podem redesenhar retroativamente uma entrada perdedora.
- Definir se a retração é medida pelo toque do pavio ou pelo fechamento. Para um impulso de alta entre L e H, uma retração de proporção r corresponde ao preço `H - r * (H - L)`; para baixa, `L + r * (H - L)`.
- Distinguir retração com duas âncoras de extensão baseada em três pontos. A convenção de projeção precisa fazer parte do protocolo e da versão dos resultados.
- Manter invalidação estrutural, distância mínima de stop da corretora, custos e risco por ativo. Um número de Fibonacci não substitui esses requisitos.
- Evitar somar Fibonacci, média e suporte como três evidências independentes quando descrevem o mesmo movimento de preço.

Essas definições são propostas de engenharia para o projeto, não uma reprodução confirmada das regras completas da aula.

### Comparação proposta

1. Congelar a estratégia de referência e a separação temporal dos dados. Períodos já pesquisados permanecem exploratórios.
2. Registrar as novas medidas e comparar com a pesquisa de retração já existente.
3. Comparar separadamente: referência; uma variante de entrada/contexto; uma variante de saída. Não mudar entrada e saída simultaneamente no primeiro teste.
4. Avaliar EURUSD e XAUUSD separadamente, com seus próprios custos, unidades, calendário e especificações de contrato. Priorizar o experimento M15/H1 que motivou a pesquisa de movimentos maiores, preservando a referência correspondente.
5. Medir resultado líquido após custos, expectativa por operação, drawdown, quantidade de entradas, estabilidade por período e oportunidades lucrativas descartadas pelo filtro. Acerto isolado não decide aprovação.
6. Exigir resultado em período separado e depois observação prospectiva com regras congeladas. Só propor promoção se houver melhoria mensurável frente à referência.

## Relação com o aprendizado

As características de retração podem enriquecer a memória de experiências e permitir perguntas como: quais profundidades funcionam melhor por regime, ativo e timeframe? Essa relação precisa ser demonstrada em dados separados. A análise conceitual do vídeo não modifica os pesos do Timestral; um eventual treinamento com novas entradas exigiria esquema de dados, versão de modelo e validação próprios.

## Conclusão

A hipótese útil é verificar se a geometria da correção acrescenta informação à estratégia existente ou melhora sua saída. Não há base nesta consulta para concluir que o nível 0,618, isoladamente, tenha vantagem preditiva ou que um exemplo em Bitcoin generalize para os dois ativos do projeto. Para reproduzir fielmente a estratégia do autor, ainda é necessário obter a transcrição ou revisar o conteúdo audiovisual completo.
