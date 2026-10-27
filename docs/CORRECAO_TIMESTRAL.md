# Recuperação da disponibilidade do Timestral

## Diagnóstico de 27/10/2026

Os checkpoints antigos continham 12 falhas exploratórias de EURUSD e duas de XAUUSD, registradas apenas como `ModelUnavailable`. Sem a mensagem original, não é possível atribuir retrospectivamente uma causa específica a cada ocorrência.

Na reprodução com candles reais, foi confirmada uma indisponibilidade por memória: o supervisor encerrou a inferência quando a RAM disponível caiu abaixo da reserva de 128 MB. O carregador original do SDK inicializava um modelo completo e depois copiava os pesos do checkpoint para ele, gerando uma alocação evitável. O modelo e as dependências também conseguiram produzir previsões válidas; não se tratava de ausência permanente dos arquivos.

## Correções

- Carregamento do mesmo checkpoint em `float32`, construindo a arquitetura em `meta` e atribuindo os tensores do arquivo `safetensors` com `strict=True, assign=True`. Evita inicializar e copiar pesos que seriam descartados. O buffer não persistente de RoPE é reconstruído como no SDK; buffers desconhecidos em `meta` são rejeitados.
- A abordagem de carregamento segue a [receita oficial do PyTorch](https://docs.pytorch.org/tutorials/recipes/recipes/module_load_state_dict_tips.html). Não modifica o SDK instalado, o arquivo de pesos, a configuração numérica ou os critérios de negociação.
- Primeira inferência usa o orçamento limitado de carregamento para permitir a leitura das páginas dos pesos mapeados. As seguintes continuam usando o timeout normal. Com a configuração atual, os limites são 180 segundos por fase de inicialização e 45 segundos por inferência já aquecida.
- Os limites de memória foram mantidos. Se faltarem recursos, o sistema informa a condição medida, preserva a reserva e tenta novamente. Não há promessa de executar sob qualquer quantidade de RAM.
- Espera entre tentativas impede recriar o processo a cada ciclo quando há falha. A espera não é estendida indefinidamente por novas consultas.
- Protocolo do processo informa fases de importação, resolução e verificação do artefato e carregamento. Mensagens de progresso não são interpretadas como previsão ou confirmação de disponibilidade.
- Falhas incluem código, fase, horário, detalhes controlados e próxima tentativa. Mensagens arbitrárias de serviços não são expostas para evitar vazamento de credenciais.
- Verificações reais em segundo plano são feitas por ativo, sem depender de um gatilho de entrada. Os ativos compartilham a inferência física; inputs e configurações permanecem separados. Após sucesso, a verificação se repete em cinco minutos; falhas respeitam seu intervalo de nova tentativa.
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
