# Treinamento: recursos, retomada e resultados

## Diagnóstico

A página `/treinamento` mostra RAM livre no **Windows**, mínimo de 384 MB para
início, uso medido do processo e horário da leitura. O serviço publica medições
no PostgreSQL em `agent_training_runtime`, a cada 15 segundos enquanto supervisiona
um processo, e a cada passagem ociosa pela fila. A medição da VM Linux não é
usada para estimar a memória do computador de treinamento.

O mínimo de início não é garantia de memória suficiente durante toda a execução.
Continuam vigentes: processo de até 768 MB, reserva de 128 MB no computador e
limite de duas horas por tentativa. A fila existente é consultada a cada minuto
pela tarefa Windows `AgenteTrader-TrainingLab` e usa trava PostgreSQL para
impedir execuções concorrentes do supervisor.

## Retomada

- Contextos: matrizes em disco, cursor confirmado a cada 160 janelas ou ao fim
  da partição, com identidade de dataset/modelo/receita e hash do prefixo salvo.
  Uma escrita interrompida não avança o cursor. Blocos não confirmados podem ser
  refeitos; contextos antigos sem manifesto de integridade não são reutilizados.
- Ajuste: checkpoint após cada época concluída, contendo pesos, otimizador,
  estados aleatórios, histórico e melhor saída selecionada pela validação.
  Uma época parcial recomeça do checkpoint anterior. Arquivos imutáveis e um
  apontador atômico impedem que uma escrita incompleta substitua um ponto válido.
- Candidato congelado: registro anterior à avaliação permite retomar a avaliação
  do mesmo candidato. Nunca volta ao ajuste após o teste. Artefatos antigos
  congelados sem relatório suficiente exigem revisão técnica.
- Previsões públicas: cada par partição/modelo concluído tem hash; na retomada
  é carregado, sem nova inferência. Arquivo alterado bloqueia a execução.
- Simulação: relatório financeiro completo é reaproveitado. Uma simulação parcial
  sem relatório final reinicia essa etapa; não há promessa de checkpoint por candle.

Falta de RAM do computador ou tempo esgotado suspende a tentativa e conserva o
mesmo `run_id`, dataset e protocolo. O supervisor aguarda pelo menos 15 minutos,
depois verifica recursos novamente. Há até três retomadas automáticas por
interrupção de recursos; espera inicial por RAM não consome essas tentativas.
Exceder memória do próprio processo, corrupção ou erro desconhecido exige revisão;
não se reinicia indefinidamente. Cancelamento explícito não é desfeito pela retomada.

## Como ler o progresso

O painel diferencia fila, preparação, espera por memória, processamento e
interrupção. Mostra o último avanço salvo, checkpoint e horário mínimo de uma
nova tentativa. Um processo pode estar ativo sem ter concluído outro bloco;
medição recente e avanço salvo aparecem separados. Uma leitura antiga não é
apresentada como prova de atividade.

## O que foi aprendido

O resumo informa receita, escopo do ajuste, melhora de previsão no teste,
resultados original/ajustado após custos quando disponíveis e conclusão.
Os motivos existentes de aprovação/rejeição permanecem visíveis. Se a triagem
de previsão impediu a simulação financeira, o painel declara isso, sem fabricar
resultado financeiro. Falha técnica não é evidência de melhora ou piora do modelo.

Não foram alterados critérios de seleção, dados reservados, custos, limites de
risco, número de épocas das receitas ou autorização de operações. O agente
de negociação usa seu fluxo independente de reconciliação e execução demo.

## Verificações

`tests/unit/test_training_recovery.py` cobre cursores, integridade, limites,
retentativas e proibição de voltar ao ajuste após congelamento.
`tests/training/test_epoch_resume.py`, no ambiente `.venv-training`, compara
treino pequeno interrompido e contínuo com igualdade exata dos pesos; também
confirma que previsões públicas concluídas não são recalculadas.
`tests/training/test_trainer_resume.py` executa o Timestral-5M fixado no projeto
com poucas janelas sintéticas, interrompe após uma época salva e confere igualdade
do artefato exportado e do histórico de perdas frente à execução contínua. Isso
valida a retomada técnica; não demonstra qualidade preditiva ou lucratividade.
`node tests/ui/training_http_contract.cjs` verifica o controle por HTTP, erros
visíveis, duplicidade de clique e apresentação de espera por RAM. Os testes
não enviam ordens nem iniciam um treinamento real pela interface.
