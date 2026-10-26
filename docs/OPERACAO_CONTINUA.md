# Operação contínua do agente

Uma sessão autônoma não possui prazo de expiração. O estado desejado fica no
PostgreSQL até o operador pedir pausa ou parada. Ausência de sinal, mercado
fechado, limites de risco ou indisponibilidade da fonte não significam encerrar
a sessão: o agente permanece aguardando e verificando as condições.

## Camadas de recuperação

1. O ciclo trata falhas de cotações, arquivos e inferência e volta a verificar a
   fonte. Não reutiliza um sinal que ficou antigo durante uma falha.
2. Exceções durante a preparação autônoma passam a `RECOVERING`, com novas
   tentativas entre 10 e 300 segundos. Mantêm sessão, geração, conta e lote.
   Erros de configuração continuam bloqueando entradas enquanto persistirem.
3. Perda da conexão PostgreSQL libera/derruba o processo e a conexão de posse.
   Keepalive TCP e detecção de conexão perdida evitam aguardar indefinidamente
   uma conexão que deixou de responder. Sem persistência, não se envia nova ordem.
4. `run_agent_supervisor.py` acompanha sinais de progresso emitidos pelo ciclo
   depois de gravar o heartbeat no PostgreSQL. Saída do processo é seguida por
   reinício. Falta de progresso por dez minutos aciona reciclagem somente da
   árvore do processo filho do projeto. O limite aumenta quando os tempos
   configurados de carga/inferência do modelo exigirem mais tempo.
   Se uma interrupção deixar um worker órfão com o lock, a recuperação exige
   heartbeat atrasado e correspondência de máquina, PID, criação do processo,
   diretório e comando do projeto. Um worker saudável ou processo alheio não é encerrado.
5. `run_agent.ps1` relança o supervisor se ele falhar. A tarefa do Windows possui
   duração ilimitada, início no login e verificação a cada minuto, sem duplicar
   instâncias. O lock PostgreSQL impede dois workers com posse simultânea.

Um timeout de chamada é uma proteção contra travamento. Ele não é um prazo de
validade da sessão. A versão autônoma não exige nova autorização a cada reinício.

## Ordens após uma interrupção

Antes de qualquer novo envio, o worker reconcilia intenções persistidas no
journal demo, inclusive quando a falha ocorreu entre o envio e o primeiro
checkpoint de conta. Essa busca ocorre também para sessões pausadas ou paradas,
para não esquecer uma ordem aceita antes do comando do operador.

`SENDING`/resposta ambígua não autorizam reenvio automático. Stops e alvos nativos
permanecem no MT5; conta, tickets, negócios e resultados precisam ser conferidos.
Resultados já aplicados não atualizam a memória novamente após reinício.

## Limites operacionais

Windows, MT5 conectado e PostgreSQL precisam estar disponíveis para analisar e
enviar novas operações. Durante indisponibilidade, o sistema aguarda ou tenta
recuperar; não promete operar sem energia, rede ou terminal. Após reinício do
Windows, a tarefa interativa inicia quando o usuário faz login e o MT5 precisa
estar disponível. Conta real permanece bloqueada.

O painel detecta perda de atividade pelo horário de recebimento do heartbeat
no PostgreSQL, sem comparar relógios de máquinas distintas. A última decisão
registrada não é prova de que o processo ainda está executando.

## Histórico diário na segunda-feira

A atualidade do histórico usa tempo de mercado aberto no calendário semanal
de Nova York. Na segunda-feira, o candle D1 em formação ainda não pode substituir
o último diário fechado na sexta-feira. O fim de semana, inclusive mudanças de
horário de verão, não deve ser contado como atraso do feed.

A correção de 26/10/2026 preserva a cobertura mínima de 95%, as tolerâncias de
atualidade e o hash dos preços. Lacunas em horário de mercado e feriados sem
calendário confirmado continuam sujeitos à validação. A verificação de cotação
ao vivo permanece separada; histórico válido não autoriza operar com tick antigo.

## Reconstrução do contexto após reinício

A inicialização percorre todos os candles necessários e atualiza os estados de
regime e tendência em cada barra. Ela evita montar relatórios intermediários de
price action, níveis e evidências, que são funções derivadas sem estado. No último
candle, o relatório completo é obrigatório; a análise operacional seguinte usa
o caminho normal. O modo interno de preparação não retorna snapshot operacional.

A equivalência foi verificada em 7.000 candles reais: estados internos iguais e
41 snapshots completos idênticos, incluindo observações após a preparação.
Na mesma execução, o consumo de CPU caiu de 206,9 para 48,6 segundos (4,26 vezes).
Isso não reduz o histórico, não muda parâmetros e não comprova lucratividade.
O registro `agent_warmup_equivalence` no PostgreSQL tem chave
`454f1605e746eb8a74b191771a3441f8085b661a908b8a4c38454df7c7fec67a`.

Ao consultar a última revisão de um candle ou a última baseline, a visibilidade
dos registros usa o relógio do PostgreSQL. Quando o chamador fornece um corte
histórico explícito, esse corte é respeitado. O período de preço continua sendo
delimitado pelos timestamps UTC dos candles. Isso evita esconder uma revisão
recém-gravada por diferença entre os relógios do cliente e do banco.

## Índice para consultas operacionais

`project_records` tem um índice por tipo e data de gravação para consultar o
estado, heartbeat e outros registros recentes sem varrer todo o journal.
Na VM, o teste SQL caiu de 3.361 ms para 0,05 ms; a leitura completa do estado
pelo cliente Python foi medida em cerca de 2 ms após a criação. São medições pontuais,
não garantia de latência futura. O índice ocupa aproximadamente 53 MB.

Em um banco existente, executar `python ensure_project_indexes.py` antes de
atualizar os serviços. Ele verifica a propriedade da tabela no banco isolado
`agente_trader`, cria o índice concorrentemente, verifica sua validade e registra
os planos de execução no PostgreSQL. Não exclui registros nem interrompe escritas.
Em bancos novos, a inicialização normal do schema também cria esse índice.
O backup PostgreSQL inclui a definição do índice.
