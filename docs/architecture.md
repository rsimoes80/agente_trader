# Arquitetura

## Estado atual

O produto é uma aplicação Python monolítica servida por `app.py` e uma interface estática. O handler conhece configurações, secrets, feed, análise, backtest e otimização. `analysis.py` retorna candidato e parâmetros de entrada; `backtest.py` é quem simula fills e aplica seus próprios limites. MT5 e Dukascopy são dois caminhos de dados distintos. O gráfico web publicado consulta uma ponte MT5 em Windows; o feed Dukascopy pertence ao painel local e agrega ticks em memória. Credenciais usam DPAPI e, portanto, são específicas ao usuário Windows.

## Alvo incremental

Preservar a aplicação atual como interface/adaptador durante a migração. Introduzir módulos de domínio sem dependências de HTTP, pandas, MetaTrader5 ou serviços externos:

```text
src/aurelia_fx/
  domain/       tipos imutáveis, Candle, Quote, Decision, RiskPlan, IDs
  ports/        MarketDataProvider, Clock, Strategy, RiskManager, Journal
  market_data/  normalização, validação, freshness e adaptadores MT5/FIX/CSV
  sessions/     calendário configurável, timezone-aware, armazenamento em UTC
  structure/    swings confirmados, BOS/sweep causais e zonas observáveis
  strategy/     plugins pequenos; primeiro pullback em tendência
  risk/         limites independentes da estratégia e do executor
  decision/     contrato de decisão, motivos e transições de estado
  learning/     experiências e propostas; nunca altera regras ao vivo
  knowledge/    ingestão versionada de regras e proveniência
  persistence/  journal e repositórios com schema/versionamento
  replay/       relógio e fonte determinísticos
  reporting/    relatório por run e auditoria
  cli/          inspect, check-data, replay e report
```

## Limites entre componentes

- Provider fornece eventos/candles tipados e metadados; não gera sinal.
- Validador bloqueia dado ausente, duplicado, fora de ordem, inválido ou atrasado.
- Features/analisadores são funções puras de dados fechados e parâmetros versionados.
- Estratégia propõe um candidato ou `NO_TRADE`, sem calcular lote nem enviar comando.
- RiskManager recebe candidato, conta e metadados do instrumento; rejeita ou emite plano de risco limitado.
- DecisionEngine registra todos os resultados e exige transições explícitas.
- Executor futuro aceita somente plano aprovado, idempotente e autorizado; neste estágio inexiste.
- Journal é append-only por run, com dados, versões, regra, motivo, estado e resultado.
- Aprendizagem propõe hipóteses para pesquisa; apenas uma promoção humana versionada pode alterar uma configuração de demo futura. Live não é alvo aprovado.

## Caminho dos dados

```text
MT5 | FIX | CSV/replay
        -> normalizar UTC -> validar qualidade/freshness
        -> sessão + estrutura/features -> estratégia
        -> decisão NO_TRADE/candidato -> RiskManager
        -> decisão NO_TRADE/sinal hipotético -> journal -> relatório
```

Os adaptadores atuais podem ser envolvidos pelas portas primeiro e substituídos depois. A migração deve manter o modo paper e nenhuma integração de ordem até haver política, testes, reconciliação e aprovação explícita separadas.


## Implemented learning foundation

`src/aurelia_fx/` now contains immutable domain types, candle validation, session identification, causal pivot/structure analysis, a read-only `MarketObserver`, an append-only SQLite `ExperienceMemory`, a fail-closed hypothetical risk gate, immutable expectation contracts, deterministic expected-versus-observed evaluation, and an offline experiment-readiness checker. SQLite is initialized at the caller-provided path; use `data/agent_memory.sqlite3` for the project-local journal (the database and WAL files are git-ignored). This is a domain foundation, not yet a wired end-to-end replay runner. Confirmation of a hypothesis does not authorize an order, and no execution adapter exists in this slice.
