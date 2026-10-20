# Implementação do plano operacional — em andamento

Objetivo integral: executar o [plano aprovado](PLANO_OPERACIONAL_E_TREINAMENTO.md),
do lote e início único até treinamento integrado, validação, simulação ao vivo
e integração de conta demo. **Este documento é um checkpoint de trabalho,
não declaração de conclusão. A tela principal foi publicada em
http://192.168.97.221:8097/ com o commit `b206738`.**

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
  Instalado como tarefa automática exclusiva `AgenteTrader-Agent`, ao login,
  com usuário limitado e proteção contra instâncias simultâneas. A pesquisa
  em curso permanece com seu processo original até terminar; a tarefa aguarda
  o lease e não substitui esse processo durante o trabalho.
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
- Registro de aprovação explícita e reaproveitamento de modelo compatível,
  condicionado ao relatório persistido e a todos os critérios de validação.
- Executor simulado com bid/ask observado, risco, prazo, pausa/parada,
  conta persistente entre sessões e recuperação de posição. Contrato e limites
  documentados em [simulação operacional](agent_live_simulation.md).
- Interface com previsão identificada/expirada por fonte, níveis da posição,
  resumo de resultados e progresso de pesquisa separado da captura mensal.

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
8. A primeira execução conjunta da versão de pesquisa produziu 167 hipóteses
   técnicas encerradas (114 desenvolvimento, 21 validação, 32 final) e 49
   hipóteses do benchmark Timestral independente. Apenas uma hipótese técnica
   cumpria também a elegibilidade operacional. Os 326 vetos técnicos de risco
   foram por relação retorno/risco líquida insuficiente; não viraram perdas de
   treino. A validação ficou abaixo do mínimo de 30 e o resultado final não foi
   consultado. O código agora prevê ampliação limitada do arquivo M5 para
   60/120/210/365 dias somente por insuficiência amostral, preservando os 30 dias
   recentes do produto e os limites numéricos do protocolo.
9. A regressão posterior passou em **169 testes** com PostgreSQL e modelo real
   habilitados. A nova ampliação automática ainda precisa de execução integral.
10. A primeira regressão após aprovação/executor passou em **184 testes**, com
    PostgreSQL e inferência real habilitados. Foram acrescentados depois testes
    do Handler HTTP e do ciclo completo do coordenador; nova regressão pendente.
    Dois testes Chrome passaram em desktop/celular. A prévia somente leitura
    também exibiu o estado real do treinamento e cotações MT5, sem erro JavaScript
    nem rolagem horizontal em 390 px. A inspeção visual encontrou textos novos
    com acentuação incorreta; foram corrigidos e o grupo de navegador passou
    novamente, incluindo uma asserção de texto em português.
11. A regressão final desta etapa executou **188 testes: 186 passaram e dois
    testes de navegador foram ignorados nesse ambiente**. Os dois de navegador
    passaram separadamente no ambiente Playwright/Chrome. PostgreSQL e modelo
    real estavam habilitados na regressão; todos os oito testes do registro,
    HTTP e coordenador simulado passaram. Isso não aprova um modelo de mercado.
12. Publicação `b206738` na VM: backup PostgreSQL concluído com `Result=success`,
    atualização fast-forward, reinício apenas do diagnóstico e container do
    projeto, configuração Nginx válida. `/`, `/mercado`, `/diagnostico`, estado
    do agente e gráfico responderam HTTP 200; CSS/JS publicados coincidem com
    os hashes locais. Comando sem autenticação foi recusado com HTTP 403.
    Chrome conferiu a página publicada em desktop/390 px sem erros JavaScript
    nem rolagem horizontal. A tarefa Windows foi registrada e conferida como
    Running/Enabled, IgnoreNew, Limited e diretório/ação deste projeto.
13. Preparação ganhou estado `WAITING_SOURCE` e nova tentativa automática em
    dez segundos para terminal indisponível ou relógio ainda não validado.
    Três testes verificam erro transitório versus configuração inválida,
    prazo/intenção do operador e o laço do serviço recuperando a mesma sessão.
    O instalador agora interrompe imediatamente em erro de permissão, inclusive
    ao consultar a propriedade da tarefa, em vez de tratar acesso negado como
    ausência de uma tarefa existente.
14. Nova regressão após recuperação automática: **191 testes executados,
    189 aprovados e dois de navegador separados por ambiente**, com PostgreSQL
    e modelo real habilitados. Nenhuma falha.

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
3. Conferir a aprovação e a simulação com uma versão que efetivamente cumpra
   os critérios de mercado. Aprovação, executor e reutilização já têm testes
   isolados; esses testes não demonstram vantagem financeira da estratégia.
4. Repetir regressão integral após as últimas mudanças e conferir a execução
   atual da pesquisa. Não usar fills retroativos na simulação ao vivo.
5. Implementar/validar adaptador demo, conta demo verificada, envio/retcodes,
   stops, reconciliação e prevenção de duplicatas; conta real continua bloqueada.
6. Conferir novamente previsão, níveis e resumo após publicação, com o serviço
   Windows atualizado; a revisão local desktop/celular já passou.
7. Ao terminar a pesquisa em curso, transferir o lease para o serviço automático
   atualizado e conferir retomada/estado. Instalação, backend, tela principal
   e verificação HTTP/navegador já foram feitos. Não interromper o replay só
   para fazer essa troca e não autorizar versão reprovada.
8. Atualizar contratos/documentação operacional e executar auditoria de conclusão
   por requisito. Não declarar o objetivo completo com os itens acima pendentes.
