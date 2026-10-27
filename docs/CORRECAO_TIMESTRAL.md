# Recuperação da disponibilidade do Timestral

## Diagnóstico de 27/10/2026

Os checkpoints antigos continham 12 falhas exploratórias de EURUSD e duas de XAUUSD, registradas apenas como `ModelUnavailable`. Sem a mensagem original, não é possível atribuir retrospectivamente uma causa específica a cada ocorrência.

Na reprodução com candles reais, foi confirmada uma indisponibilidade por memória: o supervisor encerrou a inferência quando a RAM disponível caiu abaixo da reserva de 128 MB. O carregador original do SDK inicializava um modelo completo e depois copiava os pesos do checkpoint para ele, gerando uma alocação evitável. O modelo e as dependências também conseguiram produzir previsões válidas; não se tratava de ausência permanente dos arquivos.

## Correções

- Carregamento do mesmo checkpoint em `float32`, construindo a arquitetura em `meta` e atribuindo os tensores do arquivo `safetensors` com `strict=True, assign=True`. Evita inicializar e copiar pesos que seriam descartados. O buffer não persistente de RoPE é reconstruído como no SDK; buffers desconhecidos em `meta` são rejeitados.
- A abordagem de carregamento segue a [receita oficial do PyTorch](https://docs.pytorch.org/tutorials/recipes/recipes/module_load_state_dict_tips.html). Não modifica o SDK instalado, o arquivo de pesos, a configuração numérica ou os critérios de negociação.
- O carregamento tem um prazo por ausência de avanço, renovado apenas por novas etapas ou mais bytes efetivamente verificados. Mensagens repetidas não renovam o prazo. O limite total é `min(900, 5 × load_timeout_seconds)`, nunca inferior ao prazo configurado. Na configuração atual: 180 segundos sem avanço, no máximo 15 minutos de inicialização, até 180 segundos na primeira inferência e 45 nas seguintes. A primeira inferência permite a leitura das páginas dos pesos mapeados.
- Os limites de memória foram mantidos. Se faltarem recursos, o sistema informa a condição medida, preserva a reserva e tenta novamente. Não há promessa de executar sob qualquer quantidade de RAM.
- Espera entre tentativas impede recriar o processo a cada ciclo quando há falha. A espera não é estendida indefinidamente por novas consultas.
- Protocolo do processo informa fases de importação, resolução e verificação do artefato e carregamento. Mensagens de progresso não são interpretadas como previsão ou confirmação de disponibilidade.
- O checksum SHA-256 continua lendo integralmente o arquivo, com buffer reutilizável e progresso em bytes. Alteração de tamanho ou data de modificação durante a leitura invalida a verificação. Não há substituição por um hash presumido ou apenas por metadados do arquivo.
- A reserva de 128 MB é conferida também antes de criar o processo. Se já faltar memória, ele aguarda sem iniciar uma importação que seria interrompida em seguida.
- Falhas incluem código, fase, horário, detalhes controlados e próxima tentativa. Mensagens arbitrárias de serviços não são expostas para evitar vazamento de credenciais.
- Verificações reais em segundo plano são feitas por ativo, sem depender de um gatilho de entrada. Os ativos compartilham a inferência física; inputs e configurações permanecem separados. Após sucesso, a verificação se repete em cinco minutos; falhas respeitam seu intervalo de nova tentativa.
- A primeira verificação começa com os últimos candles fechados disponíveis, antes de reconstruir todo o contexto técnico. Saúde do modelo é publicada também durante `ANALYSIS_WARMUP`. Esses cálculos servem apenas para verificar inferência; não são incorporados retroativamente às observações históricas nem liberam operações antes da conclusão do contexto.
- O resultado da verificação é aplicado pelo thread proprietário do agente. A tarefa de verificação não modifica posições, autoriza operações ou troca pesos. Durante seu carregamento, o fluxo principal continua acompanhando preços e posições; novas propostas aguardam a disponibilidade confirmada.
- Uma falha de inferência passa a produzir espera explícita pelo Timestral, em vez de ser apresentada como falha de cotação. Cache disponível não comprova que o processo esteja operacional.
- Contadores de falhas históricas são preservados. O aviso ativo desaparece após uma previsão real bem-sucedida; o histórico não é apagado.

## Evidência de validação

Testes direcionados cobrem estados de saúde e recuperação, isolamento entre ativos, não bloqueio da verificação, congelamento dos inputs, quantis inválidos, reserva de memória, progresso do protocolo, espera entre tentativas e orçamento da primeira inferência. A regressão também cobre estratégias, simulação, política demo e aprendizado contínuo.

No ambiente Timestral, testes com um checkpoint de arquitetura real e pequena verificaram igualdade exata dos parâmetros, buffers RoPE e quantis de 12 passos entre o carregador original e o otimizado, além da rejeição de checkpoint incompleto. Essa equivalência não é uma avaliação de rentabilidade nem uma comparação numérica completa do checkpoint de 209M.

A verificação operacional independente usou os perfis configurados, 256 candles M5 fechados por ativo e o mesmo processo compartilhado:

| Ativo | Modelo | Passos | Latência medida | Horário UTC |
| --- | --- | --- | --- | --- |
| EURUSD | Timestral-209M | 12 | 15.128 ms | 27/10/2026 17:13:31 |
| XAUUSD | Timestral-209M | 12 | 669 ms | 27/10/2026 17:13:32 |

Artefato original em ambos: `1456effb9927e3daa8c7234f10497e3424233869245a9c72b8ecebaf7ad2b7fa`.

Esses tempos são observações desta máquina e não um benchmark controlado. O painel do agente deve ser usado para conferir a disponibilidade atual após publicação; a prova independente não substitui essa verificação.

## Consulta no painel

Em **Evolução do aprendizado**, o bloco de coleta informa o estado atual do Timestral, última previsão real confirmada, latência e falhas históricas. Se indisponível, mostra código, etapa, horário e próxima tentativa; falta de memória inclui a RAM medida e a reserva exigida. O estado de preparação do histórico continua separado da disponibilidade do modelo.

Durante o carregamento, o painel mostra a etapa e os megabytes verificados. Nesta instalação Windows, os arquivos do modelo sob `data/models` foram marcados como sempre disponíveis no OneDrive, preservando o mesmo caminho e conteúdo. Ao replicar em uma pasta sincronizada, mantenha os pesos disponíveis localmente; o estado é controlado pelo atributo Pinned, conforme a [documentação da Microsoft](https://learn.microsoft.com/en-us/onedrive/files-on-demand-windows).
