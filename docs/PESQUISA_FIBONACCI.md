# Pesquisa prospectiva de Fibonacci

Implementação: `src/aurelia_fx/fibonacci_research.py`.

## Funcionamento

O ciclo autônomo registra oportunidades elegíveis da estratégia de pullback existente, antes de aplicar a alternativa selecionada para a operação. Esta pesquisa acompanha o caminho atual M5 com contexto H4/H1: não cria uma nova estratégia M15/H1. Não registra todos os candles como oportunidades e não modifica o gatilho atual.

Cada ativo tem um protocolo, lote, custos, estado e carteiras próprios, identificados pelo perfil do instrumento. A retomada usa o checkpoint existente no PostgreSQL. Não há comando de execução de ordens nem promoção automática neste módulo. Os pesos e as entradas do Timestral permanecem iguais.

## Três carteiras independentes

| Carteira | Entrada | Saída |
| --- | --- | --- |
| Referência | Oportunidade original | Stop e alvo originais |
| Contexto de retração | Oportunidade original, quando o fechamento está entre 38,2% e 78,6% de retração do impulso confirmado | Stop e alvo originais |
| Saída por extensão | Oportunidade original com impulso confirmado disponível | Stop original; alvo na projeção de 127,2% do impulso, a partir de sua origem |

Os valores são hipóteses de engenharia fixadas antes da coleta, não uma reprodução das regras completas do vídeo. A referência continua funcionando quando não existe âncora Fibonacci. A carteira de extensão só pode entrar com alvo adiante da entrada; a avaliação de risco do simulador também pode rejeitá-la.

Existe um quarto simulador de controle interno da saída: ele recebe o mesmo fluxo elegível por âncoras da extensão, mas mantém o alvo original. A extensão é comparada com esse controle, identificado no painel, para não atribuir à saída um efeito causado pela ausência de âncoras. A variante de retração continua comparada com a referência geral. Diferenças de duração podem produzir disponibilidade de posições distinta entre carteiras.

Cada carteira mantém uma posição por vez e os limites do simulador atual, incluindo custos, duração máxima, calendário, spread e risco. A soma das três carteiras não representa uma carteira operável com risco conjunto. Resultados são comparações de carteiras independentes sobre o mesmo fluxo de oportunidades, não pares obrigatórios de operações idênticas. As variantes podem ficar ocupadas em momentos diferentes.

## Âncoras e causalidade

- No máximo 300 candles M5 fechados; pivôs com duas barras de confirmação à direita.
- A disponibilidade é determinada por `confirmed_at`. O último par alternado disponível define o impulso; não se procura retrospectivamente um par mais favorável.
- Impulso na direção da entrada, de pelo menos 1 ATR, com origem até 96 barras atrás.
- Um extremo novo ou rompimento da origem após a ponta do impulso invalida esse contexto. Lacunas inesperadas e candles com máximas/mínimas ambíguas também impedem a variante, sem vetar a referência.
- A profundidade usa o fechamento do candle de sinal. Níveis, distâncias em ATR, âncoras e seus instantes de confirmação são congelados no registro da oportunidade. Não há redesenho de uma posição já enviada ao simulador.

Esses critérios podem reduzir bastante a amostra. O painel informa as exclusões; ausência de oportunidade não é interpretada como evidência de sucesso.

## Coleta e avaliação

O primeiro ciclo após a atualização inicia um protocolo novo por ativo. Dados antigos não são retroativamente apresentados como validação.

1. **14 dias de descoberta:** resultados separados, sem ajuste automático dos parâmetros.
2. **30 dias seguintes de validação:** novas oportunidades, com o mesmo protocolo congelado.
3. **Encerramento:** as posições pendentes terminam pelo simulador; existe uma margem de 65 minutos após o fim da coleta para avaliação.

Para uma alternativa ser sinalizada como candidata são exigidas pelo menos 30 operações encerradas em cada carteira comparada, sete dias de comparação, resultado líquido positivo, diferença diária conservadora favorável (média menos 2,58 erros padrão) e drawdown realizado não superior ao da referência. Falhas registradas ou exposições censuradas impedem essa indicação. Esse critério é uma triagem e não garante significância estatística sob dependência temporal ou múltiplos experimentos.

Depois do prazo, amostra insuficiente ou dados comprometidos resultam em **inconclusiva**. Com amostra suficiente, ausência dos benefícios exigidos resulta em **rejeitada**. Uma **candidata** ainda precisa de confirmação independente; não é ativada automaticamente. A coleta não reinicia nem aumenta o prazo para perseguir um resultado positivo.

## Persistência e painel

O checkpoint contém as carteiras, contadores e uma janela de até 1.000 observações e 2.000 resultados para consulta rápida. Os registros individuais são gravados na mesma transação do checkpoint em `project_records`, com os tipos:

- `agent_fibonacci_observation`: oportunidade, contexto, evidências, âncoras, profundidade, modelo e motivo de inclusão/exclusão por carteira.
- `agent_fibonacci_result`: resultado simulado, bruto, custos, líquido, retorno em R e identificação da oportunidade.

Chaves por conteúdo e avanço monotônico de candles evitam duplicar registros em retomadas. Uma falha do experimento restaura seu estado anterior e registra diagnóstico; o caminho principal de operações continua independente.

No painel principal, em **Evolução do aprendizado → Pesquisa Fibonacci**, são exibidos situação, datas, amostra, resultado líquido, drawdown, diferença frente à base, contexto da última oportunidade, resultados por contexto e motivos de exclusão. A amostra inicial fica separada da validação.

## Disponibilização

O Windows precisa carregar a nova versão do worker do agente; processos Python já iniciados não recarregam os módulos automaticamente. A VM precisa dos arquivos atualizados e do reinício do serviço de diagnóstico. Atualizar apenas o HTML não inicia o experimento.

Referência e limites da análise da aula: [ANALISE_FIBONACCI_YOUTUBE.md](ANALISE_FIBONACCI_YOUTUBE.md).
