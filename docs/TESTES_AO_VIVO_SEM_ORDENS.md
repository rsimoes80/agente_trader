# Observação ao vivo e encerramentos de daytrade — 28/10/2026

A observação de EURUSD está instalada como serviço independente no Linux.
Ela consulta o MT5 pela ponte, aquece o mesmo contexto da estratégia e executa
inferência real do Timestral-209M. Não inicia sessões do agente, não treina ou
promove modelos e não possui operações de execução em seu cliente da ponte.
A sessão operacional permanece parada; conta simulada e demo automática são
etapas seguintes, não iniciadas por este serviço.

## Instalar e acompanhar

```bash
python3 install_linux_workers.py --history --observe
systemctl --user status agente-trader-observation.service
journalctl --user -u agente-trader-observation.service -n 10 --no-pager
curl --fail http://127.0.0.1:8770/api/diagnostics/observation
```

O painel também encaminha a consulta privada
`/api/diagnostics/observation`. O resultado distingue `OBSERVING`, `UNAVAILABLE`,
`STALE` e `NOT_STARTED`; `orders_enabled` é sempre falso. Um recibo de status
com mais de 120 segundos fica `STALE`, sem presumir que o processo está vivo.
O serviço de usuário inicia no boot com linger e se recupera de falhas de
processo. Erros de fonte são registrados sem URLs, tokens ou credenciais e
retentados na próxima consulta; a inferência tem limites próprios de recurso
já existentes no adapter.

O intervalo padrão de consulta é dez segundos. O observer usa somente candles
fechados e gera previsões uma vez por novo candle M5. Erros de modelo têm nova
tentativa após 60 segundos. Cada novo candle fechado após o registro da sessão
gera uma decisão diagnóstica. O aquecimento não é pontuado como desempenho
prospectivo; a primeira previsão pode ser apenas diagnóstico do contexto passado.
As previsões não são probabilidades de acerto nem autorização para abrir ordem.

Registros separados no PostgreSQL:

- `live_observation_protocol`: início, política e identidade da configuração.
- `live_observation_status`: disponibilidade da fonte/modelo e heartbeat.
- `live_observation_forecast`: previsões verificadas dos horizontes 3/6/12.
- `live_observation_decision`: proposta ou motivo de espera, sem execução.

O resumo privado de cada sessão fica em `data/reports/live-observation-*/latest.json`.
Não há atualização de estatísticas de negociação com esses diagnósticos.

## Correções verificadas

O caminho de Python em `data/timestral.json` apontava ao interpretador do
sistema, após resolver o link simbólico da venv. Ele foi corrigido para o
caminho literal `.venv-timestral/bin/python`. Use o caminho absoluto da venv,
sem `realpath`/resolução do symlink: o sistema não contém os pacotes de ML.
A inferência real passou e o modelo voltou a ficar disponível após reiniciar
o observador. Foi registrada decisão de um candle fechado após a inicialização.
Isso verifica funcionamento técnico, ainda sem amostra para medir qualidade.

## Encerramentos de daytrade

A política H1 agora tem regra explícita de buffer de cinco minutos antes do
fim da união das sessões autorizadas ou antes do fechamento do calendário de
mercado, o que vier primeiro. A regra impede propostas e novas aberturas no
buffer e solicita encerramento das posições já existentes. É compartilhada
pela gestão ao vivo, conta paper e gateway demo. A reconciliação demo aplica
a regra mesmo quando o chamador não informou `force_close`.

O limite de uma hora da posição continua independente do fechamento de sessão.
A política estrita legada preserva seu comportamento para reprodução histórica.
O cálculo usa timezones das sessões e o calendário ThinkMarkets já versionado;
fechamentos excepcionais/feriados não são inferidos de preços ausentes.

Exemplos do calendário configurado, todos em UTC:

| Fronteira sintética | Início do buffer | Motivo |
| --- | --- | --- |
| Quarta-feira, 28/10/2026 | 20:55 | SESSION_CLOSE |
| Sexta-feira, 30/10/2026 | 20:50 | MARKET_CLOSE |
| Quarta-feira, 18/11/2026 | 21:55 | SESSION_CLOSE |
| Sexta-feira, 20/11/2026 | 21:50 | MARKET_CLOSE |

Os testes verificam o segundo anterior e o instante exato de cada buffer,
incluindo mudança de horário de verão, além de confirmar que o fechamento de
Londres não força saída enquanto Nova York permanece ativa. Uma posição paper
sintética foi aberta e encerrada na fronteira da sessão, e outra pelo limite
de uma hora. Novas propostas e aberturas foram recusadas no buffer.

A regra é uma solicitação de gestão, não prova de execução com MT5/rede
indisponíveis. Falhas continuam exigindo reconciliação; não se registra uma
posição como fechada sem evidência de fechamento.

## Falhas exercitadas

Com SDK e relógios simulados, sem desligar o MT5 do usuário:

- cliente do observador recusa operações SDK, `order_send` e `order_check`
  antes de qualquer chamada de rede;
- resposta perdida durante envio mantém o marcador persistente; após reiniciar
  a ponte simulada, repetir o mesmo envio é recusado antes de chamar o SDK;
- envio incerto, retomada do journal e reconciliação são exercitados no gateway;
- supervisores recuperam processos somente quando sua identidade é comprovada;
- healthcheck do modelo distingue cache, falha e inferência disponível;
- heartbeat antigo do observador não é apresentado como disponibilidade atual.

O observador real e o worker parado foram reiniciados para verificar recuperação.
A ponte permaneceu com dois envios totais registrados, ambos do teste demo
anterior: nenhum envio foi acrescentado nesta etapa. As evidências de fonte,
previsões e estado ficam no banco; nenhum dado privado foi publicado no Git.

A próxima etapa é acompanhar decisões em uma conta paper com cotações ao vivo,
antes de habilitar qualquer sessão demo automática. Esta etapa ainda não valida
rentabilidade, execução de saídas reais em falha de rede ou negociação autônoma.

## Etapa posterior

A conta paper com cotações ao vivo foi iniciada após esta etapa. Seu protocolo,
proteções contra envio e acompanhamento estão em
`TESTE_PAPER_COTACOES_AO_VIVO.md`. O observador independente continua sem
permissão de execução.
