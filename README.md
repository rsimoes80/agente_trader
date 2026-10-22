# Aurelia FX

Agente autônomo EUR/USD, execução M5 em conta **demo do MT5**, memória no
PostgreSQL e Timestral para previsão de séries temporais.

## Uso

Abra **http://192.168.97.221:8097/**, escolha o lote e clique em **Iniciar agente**.
O agente prepara 30 dias de histórico, constrói o contexto, seleciona hipóteses,
valida risco e envia entradas demo quando houver gatilho. Resultados confirmados
pelo MT5 atualizam a memória contextual. Ganho isolado não comprova uma estratégia.
Não há login do projeto nem aprovação manual por operação. Conta real é bloqueada.

Novas entradas exigem H4 e H1 com tendência confirmada e na mesma direção:
alta permite somente compra; baixa, somente venda. Conflito ou tendência indefinida
bloqueia a entrada. [Política e referências](docs/ENTRADAS_A_FAVOR_DA_TENDENCIA.md).

- **Operação `/`**: lote, iniciar/pausar/retomar/parar, gráfico e resultados.
- **Mercado `/mercado`**: gráfico detalhado, períodos e EMA, somente leitura.
- **Decisões `/diagnostico`**: decisões reais da sessão autônoma, contexto disponível,
  histórico e avaliação das previsões. Nenhuma sessão manual paralela.

Windows com usuário conectado, MT5 demo aberto e AlgoTrading habilitado são
necessários. A VM Linux hospeda a página, API e PostgreSQL. O navegador pode
permanecer fechado enquanto o agente executa.

## Componentes em produção

| Componente | Responsabilidade |
|---|---|
| `run_agent.py` / `agent_live.py` | Preparação e ciclo autônomo |
| `agent_demo.py`, `demo_gateway.py`, `demo_intents.py` | Execução demo, reconciliação e resultados |
| `autonomous_lab.py` | Seleção e memória das hipóteses por contexto |
| `run_agent_supervisor.py` / `run_agent.ps1` | Recuperação do worker |
| `mt5_provider.py` / `mt5_clock.py` | Dados MT5 e normalização UTC |
| `mt5_bridge.py` / `run_bridge_supervisor.py` | Ponte de leitura para o gráfico |
| `diagnostic_server.py` | Controles e consultas do agente atual |
| `static/operation.*`, `chart.*`, `diagnostics.*` | Interfaces publicadas |
| `historical/`, `forecasting/`, `postgres_memory.py` | Histórico, Timestral e persistência |
| `deploy/vm/` | Nginx, serviço da API e backup do projeto |

As tarefas Windows necessárias são `AgenteTrader-Agent` e
`AgenteTrader-MT5Bridge`, com execução sem prazo e recuperação automática.
O estado desejado no PostgreSQL preserva pausa e parada do operador.

## Aprendizado e pesquisa

O [laboratório de treinamento Timestral](docs/PLANO_TREINAMENTO_TIMESTRAL.md)
tem ambiente isolado e prova técnica de ajuste da saída do modelo 5M concluída.
O Timestral-209M ativo permanece com seus pesos originais. O piloto EUR/USD
treina o 5M, compara previsões e simula entradas sem ordens.
O [painel do laboratório](docs/LABORATORIO_TIMESTRAL.md) está integrado em
**http://192.168.97.221:8097/treinamento**, na mesma porta do projeto.

Os materiais em `Aprendizado/` orientam as regras e características técnicas.
Os PDFs não são treinamento direto dos pesos do Timestral. A seleção contextual
aprende com experiências e resultados; os pesos do Timestral não são ajustados
automaticamente.

A pesquisa histórica é separada do serviço de operação:

Para comparar H1 com H4+H1 no maior catálogo histórico compatível já congelado,
execute `python run_trend_experiment.py`. O relatório é gravado no PostgreSQL
(`agent_trend_experiment`) e em `data/reports/`. Esse comando não muda a política
ativa nem envia ordens. [Primeiro resultado e limites](docs/EXPERIMENTO_H1.md).

[Auditoria do classificador de regime](docs/AUDITORIA_DO_REGIME.md): bloqueios,
exemplos gráficos e alternativas medidas offline. Reprodução com
`run_regime_audit.py`, usando as dependências opcionais de `requirements-research.txt`.

[Correção de expiração e validação prospectiva](docs/ESTUDO_EXPIRACAO_E_PARAMETROS.md):
`run_regime_study.py` mantém eficiência 55% e duas confirmações em estudos separados.

```powershell
.venv/Scripts/python.exe run_research.py --days 60 --lot 0.01
```

O comando usa 30 dias para aquecimento, gera experiências, executa avaliação
histórica e grava artefatos. Não aprova versões nem envia ordens. Replay e
validação temporal continuam em `run_replay.py` ([documentação](docs/replay.md)).
`run_history.py` e o coletor opcional `run_timestral.py` são ferramentas de coleta
ou pesquisa; não precisam rodar em paralelo para iniciar o agente.

## Instalação e dados

Dependências operacionais: `requirements.txt`. O ambiente isolado do Timestral
usa `requirements-timestral.txt`; pesos e revisão são configurados em
`data/timestral.json`. Configuração PostgreSQL e segredos da ponte ficam fora do Git.

Atualizações preservam `data/knowledge`, modelos, referências e registros do
PostgreSQL. Implementações anteriores permanecem no histórico do Git; suas
instruções antigas não representam o fluxo atual.

## Documentação atual

- [Ciclo autônomo demo](docs/CICLO_AUTONOMO_DEMO.md)
- [Operação contínua](docs/OPERACAO_CONTINUA.md)
- [Recuperação do gráfico](docs/RECUPERACAO_DO_GRAFICO.md)
- [Banco e backup](docs/postgresql.md)
- [Referência MT5 Python](DOC_METATRADER5_PYTHON.md)
- [Revisão e redução do escopo](docs/REDUCAO_DO_ESCOPO.md)
