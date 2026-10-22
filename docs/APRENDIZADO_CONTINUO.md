# Aprendizado contínuo do Agente Trader - IA

## Uso

Escolha o lote e clique em **Iniciar agente**, na conta demo. Mantenha o Windows,
o MT5 e a VM ligados. A página pode ser fechada. Não é preciso solicitar novas
provas, analisar gráficos manualmente ou aprovar cada hipótese.

O painel principal mostra a estratégia atual, candles novos observados,
oportunidades, resultados aprendidos e alternativas em simulação. O painel
**/treinamento** acompanha o retreinamento dos pesos. **Antecipar treino** é
opcional; o agendador funciona sem esse clique.

## 1. Memória operacional

Cada resultado confiável da sessão atualiza as estatísticas do contexto:
fonte/modelo, regime, direção, sessão e faixa de volatilidade. Na demo, o resultado
vem dos negócios do MT5, com custos. No modo simulador, vem das cotações
observadas. As duas contas e as simulações paralelas são memórias separadas.

As estatísticas recentes usam meia-vida de 20 operações. Uma perda isolada não
troca a estratégia. Com pelo menos dez resultados e recompensa recente abaixo de
-0,25R, o contexto é suspenso. As simulações continuam; a recuperação exige oito
resultados novos favoráveis nesse contexto. Não há martingale, aumento automático
de lote nem relaxamento das regras H4/H1 e de risco.

Resultados antigos sem versão da alternativa não são atribuídos retroativamente
à nova estratégia. A memória anterior permanece no banco. Lote ou modelo novos
reiniciam a comparação de carteiras; experiências comparáveis continuam
identificadas por sua origem e versão.

## 2. Alternativas que realmente mudam a operação

O catálogo inicial desta implementação contém:

| Alternativa | Diferença operacional |
|---|---|
| Base | Pullback atual, alvo 2,5R |
| Alvo 3R | Mesmo gatilho e stop, alvo maior |
| Alvo 3,5R | Mesmo gatilho e stop, alvo maior |
| Confirmação Timestral | Só entra com previsão favorável em 15 e 30 minutos |
| Candle forte | Corpo direcional de pelo menos 0,5 ATR e alvo 3R |

São hipóteses de engenharia explícitas, não fórmulas atribuídas aos livros.
O agente não escreve código arbitrário nem inventa uma estratégia sem limites.

Cada alternativa tem uma carteira virtual independente, uma posição por vez,
mesmo lote e limites existentes. O sinal usa apenas candles fechados; o resultado
só aparece depois do movimento observado. Spread, slippage e comissão entram
na simulação. Não existe obrigação de gerar entradas em RANGE ou contra H4/H1.

A troca automática exige pelo menos sete dias, sete datas com resultados,
20 operações por versão, lucro positivo, comparação diária conservadora
favorável à alternativa e drawdown realizado sem piora. O contexto atual precisa
de pelo menos oito observações favoráveis. Estes são critérios de engenharia de
um experimento demo; não uma probabilidade calibrada ou garantia de lucro.

Uma alternativa deixa de ser usada quando a evidência já não a sustenta.
Lacunas durante uma exposição censuram a experiência e reiniciam a comparação;
não são preenchidas com ganhos estimados. Resultados em simulação nunca entram
no saldo da corretora.

## 3. Aprendizado dos pesos do Timestral

`AgenteTrader-TrainingLab` verifica a fila a cada minuto. Com o agente iniciado,
faz a atualização histórica e solicita um treino com pelo menos **288 candles
M5 novos** e intervalo de **24 horas**. Passagem do tempo sem candles não basta.
Falha temporária de fonte é reavaliada em 15 minutos.

Cada execução congela um dataset novo, usando até 180 dias disponíveis, cortes
cronológicos, hashes e exclusão das janelas reservadas registradas. O primeiro
piloto congelado continua arquivado; não é repetido como se fossem dados novos.
Os dados históricos já pesquisados são identificados como conhecidos.

O catálogo de treino alterna três receitas registradas antes da execução:
saída do 5M com LR 0,00001 por três épocas, LR 0,00003 por três épocas e LR
0,00001 por cinco épocas. O backbone continua congelado. A validação escolhe a
época; o teste não escolhe hiperparâmetros. Uma nova tentativa usa dados novos.

Se a previsão falhar na triagem, o ciclo termina sem gastar CPU em replay
financeiro. A memória e os relatórios são preservados, e a próxima receita será
avaliada no próximo ciclo. O agente em operação continua independente.

## 4. Validação futura, troca e retorno automáticos

Um candidato só entra nessa etapa após passar a previsão retrospectiva e o
replay com custos. O protocolo é registrado antes da primeira previsão futura.

O agente compara, nos mesmos dados novos:

- 5M original;
- 5M ajustado;
- modelo efetivamente em operação, inicialmente o 209M.

Um processo CPU pequeno compartilha o backbone entre as duas cabeças 5M. Os
alvos são avaliados somente quando fecham. Previsões e resultados têm hashes e
ficam no PostgreSQL. Para entradas virtuais prospectivas, usa cotação nova
depois da inferência; não utiliza retroativamente a abertura já passada.

A aprovação exige pelo menos 200 previsões avaliadas, sete dias corridos,
20 dias distintos para a comparação temporal e 20 operações confiáveis por
versão. Também exige melhora frente ao original e ao modelo ativo, lucro e
drawdown aceitáveis, nenhuma exposição pendente e ausência de resultados
incertos. Sem amostra suficiente em 45 dias, o candidato é encerrado sem promoção.

Quando aprovado, o release salva a configuração anterior e troca a referência
automaticamente. O agente carrega a versão quando estiver sem exposição; não
reinicia ou perde uma posição para trocar pesos. Falta de RAM bloqueia a troca
e novas entradas até o modelo estar disponível, preservando a reconciliação.

Se uma versão ajustada acumular 20 resultados recentes, média abaixo de -0,25R
e mais de 70% de perdas, há solicitação automática de rollback, aplicada sem
exposição. O retorno usa a configuração anterior salva; não cria pesos novos.

## Persistência, recursos e limites

Memórias grandes são snapshots por conteúdo, referenciados pelos checkpoints,
para não duplicar todo o aprendizado a cada cotação. A gravação da referência e
do checkpoint ocorre na mesma transação. Ausência ou alteração de um snapshot
gera erro de integridade; não reinicia a memória silenciosamente.

Os registros incluem `agent_learning_checkpoint`, eventos de aprendizado,
`agent_automatic_training`, `agent_model_study_protocol`,
`agent_model_study_forecast`, `agent_model_study_score` e
`agent_model_study_trade`. Os artefatos locais ficam em `data/training`.

Treinos usam um thread, prioridade baixa e a supervisão de recursos já existente.
O laboratório não envia ordens. Somente o executor demo existente envia ordens,
depois das verificações de conta, tendência, lote e risco. O sistema não habilita
conta real, não altera os PDFs, não modifica o classificador de regime para
fabricar oportunidades e não prova lucratividade por ter terminado um treino.

## Evidência da ativação em 22/10/2026

A sessão demo existente foi preservada e o worker atualizado sem posições ou
ordens abertas. O protocolo `continual-context-v1` foi registrado às 17:22 UTC,
com cinco alternativas. A memória começa a contar observações posteriores ao
registro; os três trades de versões anteriores permanecem arquivados.

O primeiro retreino foi solicitado pelo agendador, sem clique no painel:
`bd4104b6-9046-422e-8cdb-bc877b6e4719`. Foram detectados 567 candles novos e
congelados 37.065 candles na janela móvel: 1.617 janelas de treino, 360 de
validação e 361 de teste. A melhora no pinball do teste foi 0,0528%, abaixo do
mínimo, com evidência diária inconclusiva. O candidato foi reprovado; o replay
financeiro foi dispensado pela triagem e o 209M não foi substituído.

Pico observado do subprocesso de treino: 379,5 MB; etapa supervisionada de
29,56 segundos. A tarefa automática terminou com código zero e permanece
agendada. Resultados da prova inicial e desse ciclo não são comparações diretas:
os períodos e a composição dos testes são diferentes.
