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
