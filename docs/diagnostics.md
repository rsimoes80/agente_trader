# Painel de diagnóstico de regimes

URL: `http://192.168.97.221:8097/diagnostico`.

O painel usa o PostgreSQL do projeto e preserva a separação entre replay histórico e
observação ao vivo. Selecionar uma execução evita somar replays do mesmo dataset.
Filtros de regime, sessão, timeframe de execução, intervalo e motivo restringem a auditoria.
O timeframe de contexto do classificador aparece separadamente.

## Revisão humana

Selecione uma observação para examinar candles, limites da faixa, evidências, ausências,
parâmetros e razão registrada para NO_TRADE. O gráfico termina no candle da decisão.
A visualização de contexto agrega somente buckets completos, sem preencher candles ausentes.
As linhas de faixa começam na detecção; não são projetadas retrospectivamente para trás.

Revisões humanas são informadas e retrospectivas: a saída do modelo está visível.
São registradas como novos eventos em `project_records` (`human_regime_review`), com
revisor, horário, justificativa e referência/versionamento do snapshot. Não constituem
ground truth independente nem autorizam treino, promoção ou alteração do classificador.
Correções devem ser novas revisões; o histórico é preservado.

## Sensibilidade offline

O formulário aceita até três janelas de 6–80 barras do contexto, comparadas com a
configuração original da execução. Apenas runs identificados como `development` por
um artefato de validação temporal concluída são aceitos. Runs sem partição, live,+validação e holdout são rejeitados. Os candles devem corresponder exatamente ao hash
do dataset e às decisões daquele run. Não é usado um diretório arbitrário do servidor.

Cada solicitação congela plano e parâmetros no PostgreSQL antes da execução em segundo
plano. Resultados incluem UNKNOWN, mudanças por 100 atualizações do contexto, duração
mediana e concordância com baseline. Esses números não medem acurácia nem lucro;
menos UNKNOWN não é objetivo isolado. Uma comparação por vez, sem seleção automática.
Jobs interrompidos por reinício precisam ser solicitados novamente; não há retomada parcial.

## Observação contínua

`agente-trader-diagnostics.service` executa no Linux com usuário rafael e Python isolado.
A API escuta somente `127.0.0.1:8770`; o Nginx existente publica a rota no endereço 8097.
O observador consulta a ponte MT5 existente a cada 20 segundos e usa somente candles
M5 fechados; hierarquia inicial H1/M30/M15/M5. Um lease PostgreSQL evita coletores duplicados.

O primeiro carregamento reconstrói estado com até 2.000 candles e registra a observação
atual. Depois, o checkpoint persistente permite recuperar novos candles, sem apagar o
passado. Candles, snapshots, evidências, NO_TRADE, experiências e janela visual congelada
são gravados atomicamente. A janela congelada preserva o que estava disponível na decisão,
mesmo que o provedor revise o histórico depois. Durante recuperação, spread histórico é
usado para candles antigos; a cotação atual é usada apenas na observação corrente.

Ponte, Windows e terminal MT5 conectado continuam necessários para novos dados.
Indisponibilidade/atraso fica explícito no painel; não vira cotação simulada. O serviço
retenta sem emitir ordens e inicia automaticamente com a VM. O classificador não recebe
mudanças dos experimentos ou das revisões. Não existe gateway de execução neste serviço.

## Operação

```sh
sudo systemctl status agente-trader-diagnostics
sudo journalctl -u agente-trader-diagnostics -n 50 --no-pager
sudo systemctl restart agente-trader-diagnostics
curl http://127.0.0.1:8770/health
```

O banco precisa estar configurado em `data/database.json` ou `AGENTE_TRADER_DATABASE_URL`.
Senhas não são entregues ao navegador. POSTs exigem nonce da sessão e origem permitida.
O painel permanece acessível à rede local existente; não adiciona contas de usuário.
Backup: `bash deploy/vm/backup-postgres.sh`.

## Primeira auditoria

Veja [auditoria inicial e comparação 16/20/24](diagnostic_initial_audit.md). O motivo exibido é o primeiro bloqueio registrado, não uma lista de todos os gates possíveis. A matriz permite separar sessão, execução e contexto. Concordância humana considera a última revisão por pessoa/snapshot e não equivale a acurácia independente.

O observador rejeita horários futuros além de cinco segundos de tolerância de relógio; não corrige automaticamente fuso do broker. Quando a ponte responde mas o SDK não entrega histórico, o painel distingue essa condição de uma ponte desligada.
