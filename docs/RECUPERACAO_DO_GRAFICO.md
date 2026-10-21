# Recuperação do gráfico MT5

O gráfico depende da ponte de leitura no Windows, separada do worker que opera
a conta demo. A parada dessa ponte pode interromper o gráfico mesmo com o agente
ativo. A tarefa `AgenteTrader-MT5Bridge` passa a ter início no login e verificação
a cada minuto, sem prazo de execução nem instâncias duplicadas.

`run_bridge_supervisor.py` monitora `/health` a cada cinco segundos. Se o processo
terminar, ele é relançado. Se não responder por 120 segundos, somente sua árvore
de processos é reciclada. Um processo remanescente só é adotado depois de conferir
o PID, o comando `mt5_bridge.py` e o diretório deste projeto. Listeners sem
identidade confirmada não são encerrados.

O SDK continua serializado na thread principal da ponte. Conexões HTTP têm prazo
para leitura, e desconexão do navegador não encerra o servidor. Nenhum desses
componentes envia ordens.

A página limita as requisições a 12 segundos e evita consultas de cotação
simultâneas. Após falha, tenta novamente e mantém o último gráfico conhecido com
aviso de desatualização. O último conjunto de 120 candles também é salvo no
navegador por até sete dias para sobreviver a uma recarga durante indisponibilidade.
Esse cache contém preços e metadados de horário; não contém token nem credencial.
Projeções e níveis operacionais não são exibidos como atuais sobre dados
desatualizados. Sem cache, a tela aguarda os dados reais; não gera candles fictícios.

Testes cobrem reinício por ausência de saúde, adoção sem duplicação, falhas
transitórias, queda/recarga/retorno da ponte e timeout de requisição no navegador.
Indisponibilidade real de Windows, rede ou MT5 ainda pode interromper a atualização;
essas proteções fazem a retomada automática e tornam explícita a idade dos dados.
