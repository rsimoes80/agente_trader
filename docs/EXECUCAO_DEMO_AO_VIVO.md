# Execução e aprendizado na conta MT5 demo — 28/10/2026

A execução automática EURUSD foi habilitada por autorização explícita do
operador, após encerrar a sessão paper e confirmar que a conta MT5 conectada
era demo, sem posições ou ordens pendentes, com AlgoTrading e Python permitidos.
O lote da nova sessão é 0,01. Não foram alterados os limites de risco ou a
exigência de entradas a favor do H1 confirmado.

## Estado e acompanhamento

A nova sessão usa `mode=demo` e `execution_profile=autonomous_demo`. A autorização
persistida é vinculada à identidade da conta, terminal, sessão e relógio; ela
não é transferida para outra conta. A ponte e o gateway recusam contas reais.
O estado chegou a `ANALYZING`, com Timestral disponível. A decisão observada no
aceite foi `TREND_CONFIRMATION_REQUIRED`, sem posição aberta. Isso significa
que a execução está habilitada, mas não é uma ordem de abrir imediatamente.

No painel, confira o modo demo, estado e decisões. Ordens efetivamente
executadas aparecem no MT5; resultados, custos, tickets e reconciliação ficam
no PostgreSQL. `Parar` no painel solicita encerrar a exposição pertencente à
sessão e cessar novas entradas. Não fecha posições manuais ou de outro agente.

## Transição reproduzível

Com todas as sessões paradas e sem exposição pendente:

```bash
python3 install_linux_workers.py --history --observe --demo-execution
systemctl --user restart agente-trader-agent.service
docker compose -f data/provisioning/compose.json up -d --build api
```

Esse comando configura o transporte; o START demo é uma ação separada. Nesta
VM o START foi emitido após a verificação da conta e persistido com autorização
do operador. O protocolo privado fica em
`data/provisioning/verification/demo-live-session.json` e no registro
`demo_live_protocol` do PostgreSQL. Não publique esse diretório.

A opção `--demo-execution` é mutuamente exclusiva com `--paper-test`. Ela
persiste `paper_test=false`, configura `AURELIA_MT5_READ_ONLY=0` e remove somente
o drop-in paper padrão criado durante os testes. Um drop-in personalizado é
preservado e causa recusa da transição. A configuração dos serviços não inicia
sessões por si só e a transição recusa sessão ativa/exposição pendente.

## Como o agente aprende

Quando a corretora confirma o fechamento, `NativeDemoAccount.sync` calcula
resultado líquido e resultado em risco a partir da evidência dos deals e chama
o aprendizado da hipótese. O resultado é aplicado uma vez, com marcador
persistente; reconciliar novamente não duplica a recompensa. Os registros
separam operações demo da sessão, carteiras shadow e evidência legada.

O aprendizado mantém estatísticas por contexto/variante, registra acertos e
erros, pode suspender contextos com resultados negativos e compara alternativas
sob os critérios já definidos. Uma perda isolada não reescreve a estratégia nem
é garantia de que a próxima operação terá lucro.

Para esta primeira avaliação demo, o modelo numérico continua com seus pesos
originais fixos. `freeze_weights=true` mantém o timer de treinamento pausado,
independentemente da liberação do envio. O aprendizado de hipóteses e resultados
continua ativo. Ajustar pesos e promover releases é um processo distinto e
não foi habilitado por esta transição.

## Proteções preservadas

- Compra somente com H1 `BULL_CONFIRMED`; venda com H1 `BEAR_CONFIRMED`.
- Dados/relógio validados, spread e relação retorno/risco exigidos.
- Stop/alvo, limites de perda, drawdown, entradas diárias e exposição.
- Limite de tempo e gestão antecipada do fim da sessão/mercado.
- Checagem de conta demo e permissões a cada operação do gateway.
- Journal antes do envio, proibição de duplicação e reconciliação de incerteza.

Falha de rede/terminal não prova que uma posição foi fechada. O agente conserva
os marcadores e reconcilia antes de repetir ações. Mantenha Linux, Windows,
ponte e MT5 disponíveis para acompanhamento; nenhuma entrada é forçada para
fazer o terminal mostrar atividade.
