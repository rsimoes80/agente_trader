# Implementação do plano operacional — em andamento

Objetivo integral: executar o [plano aprovado](PLANO_OPERACIONAL_E_TREINAMENTO.md),
do lote e início único até treinamento integrado, validação, simulação ao vivo
e integração de conta demo. **Este documento é um checkpoint de trabalho,
não declaração de conclusão. A tela principal nova ainda não foi publicada.**

## Implementado no código, com validação parcial

- Tela `static/operation.html`: lote, início/pausa/retomada/parada, etapas reais,
  gráfico simples, decisão, posição e quadro de treinamento. Diagnósticos
  anteriores preservados como área avançada.
- Sessão de acesso por cookie HttpOnly/SameSite, prazo de oito horas, limite
  de tentativas e logout. Reutiliza a credencial privada de operador, sem
  embuti-la no JavaScript. Infraestrutura HTTP continua restrita à LAN existente.
- `OperationControl`: comandos e estados persistidos no PostgreSQL existente,
  idempotência, geração de processamento e proteção contra um trabalho antigo
  sobrescrever uma retomada. Modo permitido neste momento: somente `paper`.
- `run_agent.py`: consumidor Windows com lease exclusivo, validação do lote no
  contrato real do símbolo, captura mensal e preparo do arquivo de pesquisa.
  Ainda não instalado como tarefa automática nesta entrega; há instaladores.
- Novo arquivo M5 de pesquisa, separado da baseline mensal, com 30 dias de
  aquecimento. `frozen_candles` confere hash e instante de persistência.
- `agent_strategy`: setup de pesquisa versionado, variáveis V4 + Timestral,
  referência aos conceitos conferidos e parâmetros explicitamente de engenharia.
- `agent_dataset`: hipóteses contrafactuais, previsões em lotes de até oito,
  custos/saídas pelo simulador existente e benchmark Timestral com agenda fixa.
- `agent_model`: regressão regularizada, calibração temporal de desenvolvimento,
  esquema completo de features e rejeição de esquema incompleto.
- `agent_validation`: divisões 60/20/20, expurgo de saídas que cruzam fronteiras,
  walk-forward no desenvolvimento, seleção de limiar na validação e teste final
  condicionado. Não promove modelo automaticamente.
- Risco e simulador aceitam unidades fixas correspondentes ao lote escolhido;
  bloqueiam excesso de risco em vez de redimensionar silenciosamente.

## Evidências reais e decisões de pesquisa

1. A preparação mensal real passou, seguida de um arquivo de cerca de 12 mil
   candles M5 cobrindo 60 dias, incluindo aquecimento.
2. O primeiro replay da implementação encontrou zero candidatos: havia oito
   falsas lacunas semanais nos contextos H4/D1, causadas pelo descarte de barras
   encurtadas nas bordas de fechamento e abertura semanal.
3. A fonte também encerra sexta-feira cinco minutos antes da convenção genérica.
   Foi criado calendário específico, sem inferir fechamento a partir de falta
   de dados: [ThinkMarkets, horário oficial](https://support.thinkmarkets.com/hc/en-gb/articles/11613376227601-Market-hours).
4. No mesmo arquivo, agregação de calendário específico produziu 260 barras H4
   e 50 D1, sem lacunas inesperadas; os dados M5 também ficaram sem lacunas sob
   esse calendário. Nenhum candle ausente foi preenchido. A classe nova é
   injetada apenas no novo fluxo, preservando o diagnóstico legado.
5. O recorte de H4 continuou sem oportunidades de tendência no mês. Um experimento
   separado com H1 operacional e H4/D1 superiores produziu uma experiência fechada,
   insuficiente para treino. Os experimentos anteriores permanecem no banco.
6. A versão atual separa padrões de pesquisa de elegibilidade operacional: pode
   simular hipóteses com contexto UNKNOWN para estudar resultados, marcadas como
   inelegíveis para produção. O benchmark independente é uma experiência separada.
   Carteiras técnicas/conjuntas continuam excluindo candidatos inelegíveis.
7. As primeiras implementações passaram em 166 testes, com PostgreSQL e modelo
   reais habilitados. Depois, três testes adicionais verificaram a separação
   pesquisa/produção. O grupo Timestral passou em 23 testes, incluindo duas
   séries distintas no mesmo lote real de inferência e contextos de comprimentos
   diferentes. Mudanças posteriores ainda exigem regressão final.

## Regras que permanecem

- Não converter NO_TRADE em perda nem contar repetições de replay como novos
  trades independentes. Amostras contrafactuais podem se sobrepor; isso é informado.
- O modelo em treino não autoriza operações. UNKNOWN continua bloqueando as
  entradas da estratégia operacional.
- Não declarar calibração perfeita, vantagem estatística ou reserva globalmente
  inédita para dados já inspecionados. A primeira pesquisa é retrospectiva e
  candidata apenas à simulação.
- Não rebaixar limites de risco ou suficiência para fazer o relatório aprovar.
- Envio de ordens permanece desabilitado no fluxo novo. Os módulos existentes
  do projeto continuam disponíveis, sem mudanças em outros projetos da VM.

## Pendente para concluir o plano integral

1. Concluir e conferir o replay atual da versão contrafactual/batched, inspecionar
   amostras, custos, elegibilidade e comparações. Se faltar amostra, ampliar
   histórico M5 de pesquisa dentro de um protocolo explícito e limitado;
   a baseline mensal dos sete períodos deve continuar separada.
2. Testar as fronteiras temporais, benchmark independente, seleção de limiar,
   bloqueio de final e resultados dos relatórios. A última implementação ainda
   precisa de verificação integral com dados reais e regressão final.
3. Implementar registro e aprovação explícita da versão candidata para simulação,
   reutilização de versão compatível e exposição dessa aprovação na interface.
4. Implementar simulação ao vivo com cotações observadas, gestão de posição,
   persistência/recuperação, perda de fonte, parada e limites de risco. Não usar
   fills retroativos de abertura de candle como se fossem execuções ao vivo.
5. Implementar/validar adaptador demo, conta demo verificada, envio/retcodes,
   stops, reconciliação e prevenção de duplicatas; conta real continua bloqueada.
6. Acrescentar resumo de resultados e previsão ao gráfico principal, revisão
   de usabilidade desktop/celular e mensagem objetiva para cada bloqueio.
7. Instalar o serviço Windows do agente, publicar backend/arquivos na VM,
   trocar o índice Nginx para a tela principal nova e verificar o fluxo completo.
8. Atualizar contratos/documentação operacional e executar auditoria de conclusão
   por requisito. Não declarar o objetivo completo com os itens acima pendentes.
