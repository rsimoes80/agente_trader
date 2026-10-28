# Conta paper com cotações ao vivo — 28/10/2026

A sessão EURUSD foi iniciada explicitamente em `mode=paper` e
`execution_profile=autonomous_paper`. Ela usa cotações atuais da ponte MT5,
lote virtual de 0,01 e saldo inicial sintético de US$ 10.000. Isso não corresponde
a saldo, ordem ou posição da conta MetaTrader. A estratégia continua exigindo
H1 confirmado e lado compatível com a tendência.

## Proteções da etapa

O worker está configurado com `AURELIA_MT5_READ_ONLY=1`. O adaptador remoto
seleciona o cliente restrito a dados de mercado; chamadas SDK de execução são
recusadas antes da rede. Com essa variável, comandos START em modo demo também
são recusados. `mode=paper` continua utilizando somente `PaperAccount`, nunca
`NativeDemoAccount`. A ponte permaneceu com os dois envios registrados do teste
demo anterior; nenhum novo envio foi necessário para iniciar esta sessão.

O timer de treinamento foi desabilitado para manter os pesos fixos durante a
avaliação. O modelo selecionado é o Timestral-209M original com revisão fixada.
A observação independente continua ativa. As hipóteses e resultados paper são
registrados separadamente, sem convertê-los em prova de execução no broker.

A configuração é persistente para reinícios:

```bash
python3 install_linux_workers.py --history --observe --paper-test
```

O instalador salva `paper_test=true` no JSON privado, aplica o transporte
somente de leitura aos serviços, mantém o treinamento automático desabilitado
e atualiza o ambiente da API no Compose. Ele não inicia uma sessão por conta
própria. O START paper foi emitido separadamente após conferir ausência de
sessão/exposição pendente e validar o bloqueio de envio.

Nesta VM há também um drop-in `paper-test.conf` do serviço do agente reforçando
o mesmo bloqueio. Não remova essas proteções como parte de um teste paper.
Uma etapa posterior de demo automática requer encerrar a sessão paper e revisar
explicitamente o protocolo, a configuração persistida, o drop-in e o timer.

## O que acompanhar

No painel, escolha EURUSD e acompanhe o estado, decisões e diagnósticos:

- `ANALYSIS_WARMUP`: preparação dos indicadores com dados anteriores.
- `ANALYZING`: fonte e modelo disponíveis; aguardando setup/risco elegíveis.
- `POSITION_OPEN`: posição exclusivamente virtual em acompanhamento.
- `RECOVERING`/`WAITING_SOURCE`: fonte indisponível ou outra falha recuperável.

Consultas somente de leitura:

```bash
curl --fail 'http://127.0.0.1:8770/api/diagnostics/agent?symbol=EURUSD'
curl --fail 'http://127.0.0.1:8770/api/diagnostics/decisions?symbol=EURUSD'
journalctl --user -u agente-trader-agent.service -n 20 --no-pager
```

O resumo do protocolo desta execução fica privadamente em
`data/provisioning/verification/paper-live-session.json`. O journal PostgreSQL
preserva comandos, checkpoints, decisões e eventos. Parar a sessão pelo painel
encerra o acompanhamento da posição simulada com cotação observada; não envia
ordens ao MT5.

## Critérios de avaliação

Registrar propostas, bloqueios, entradas efetivamente aprovadas, custos, saídas
por stop/alvo/tempo/sessão, resultados líquidos e cobertura das cotações.
O limite de uma hora e o buffer de encerramento daytrade continuam aplicados.
Preenchimentos são simulados com bid/ask observado, slippage e comissão de
pesquisa; não são garantias de preço real. Lacunas na amostragem permanecem
marcadas como cobertura incerta e são excluídas de recompensas confiáveis.

No aceite da inicialização, o estado chegou a `ANALYZING`, com inferência
`AVAILABLE`, zero operações encerradas e nenhuma posição virtual aberta.
A primeira decisão após o aquecimento podia estar fora do prazo de 90 segundos
(`SIGNAL_TOO_OLD`); ela não autoriza entrar retroativamente. A sessão aguarda
novos candles e condições válidas, sem forçar entradas para produzir amostra.

O início técnico não valida rentabilidade. O teste deve acumular decisões e
operações prospectivas antes de avaliar desempenho ou passar a demo automática.

## Transição posterior autorizada

A sessão paper foi encerrada por solicitação do operador e substituída por
execução demo. Consulte `EXECUCAO_DEMO_AO_VIVO.md` para o estado posterior e as
proteções preservadas. Este documento registra o protocolo da etapa paper;
não representa o modo atual após essa transição.
