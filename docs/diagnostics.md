# Decisões do agente

Acesse `http://192.168.97.221:8097/diagnostico`.

O painel consulta as decisões gravadas pelo próprio agente na sessão autônoma
atual: horário UTC, ação, hipótese e motivo. Clique em uma linha para consultar
o contexto técnico e os candles conhecidos naquele instante, quando registrados.
Registros antigos sem esses campos são identificados; não são reconstruídos.

Esta tela é somente leitura. Não possui sessão manual, aprovação de modelo,
revisão humana obrigatória nem envio de ordens. Os controles do agente estão
na página principal.

A avaliação Timestral é uma análise das previsões de preços, separada dos
resultados financeiros das operações. Histórico e memória permanecem no
PostgreSQL; a retirada dos controles antigos não exclui seus registros.
