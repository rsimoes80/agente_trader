# Arquitetura atual

## Fluxo operacional

Lote -> 30 dias de historico MT5 -> contexto e tendencia -> hipotese -> risco
-> entrada demo -> reconciliacao MT5 -> resultado -> memoria contextual.

## Windows: dados, operacao e treinamento

- `mt5_provider.py`: candles, cotacoes e normalizacao UTC.
- `mt5_bridge.py` e `run_bridge_supervisor.py`: ponte de leitura dos graficos.
- `run_agent.py`, `agent_live.py` e `run_agent_supervisor.py`: ciclo autonomo,
  estado persistente e recuperacao do worker.
- `agent_strategy.py`, `entry_trend.py` e motores de percepcao: regime,
  estrutura, H4/H1 confirmados, gatilho M5 e direcao permitida.
- `agent_demo.py`, `demo_gateway.py`, `demo_intents.py`: execucao somente demo,
  reconciliacao e protecao contra duplicidade.
- `agent_model.py` e `forecasting/`: previsoes Timestral em ambiente isolado.
- `continual_learning.py`, `autonomous_lab.py` e `learning_storage.py`: memoria
  de resultados e comparacao de cinco alternativas em simulacao paralela.
- `run_training_lab.py` e `training/`: dados novos, ajuste do modelo 5M,
  validacao retrospectiva/prospectiva, promocao automatica e rollback.

As tarefas `AgenteTrader-Agent`, `AgenteTrader-MT5Bridge` e
`AgenteTrader-TrainingLab` independem do navegador. MT5 e Windows precisam
permanecer ligados; o supervisor recupera processos, mas nao substitui o terminal.

## VM Linux: interface e persistencia

- `diagnostic_server.py`: API do controle autonomo e consultas.
- `static/`: operacao, grafico, diagnostico e treinamento, na porta 8097.
- `postgres_memory.py`, `historical/` e repositorios: PostgreSQL como banco
  operacional; historico, decisoes, experiencias e metadados dos experimentos.
- `deploy/vm/`: Nginx, API, backup e estudo de regime separado da operacao.

Pesos de modelos e ambientes Python ficam em arquivos locais, fora do Git.
Snapshots de aprendizado usam referencias por hash para evitar repetir o mesmo
conteudo em cada checkpoint. Dados e ordens nao sao apagados pela limpeza.

## Pesquisa necessaria ao aprendizado

Replay, simulador, validacao temporal e estudos de tendencia/regime continuam
separados das ordens demo. Eles medem alternativas com custos e dados separados;
nao substituem o resultado confirmado pelo MT5. O laboratorio automatizado usa
simulacao para validar modelos antes de permitir uma substituicao.

As literaturas e `data/knowledge` preservam conceitos e proveniencia. PDFs nao
sao treinamento direto dos pesos. O aprendizado operacional e os retreinos sao
explicados em [APRENDIZADO_CONTINUO.md](APRENDIZADO_CONTINUO.md).

## Limites mantidos

Tendencia confirmada H4/H1, regime TREND, lote escolhido, limites de risco,
candles fechados, identidade da fonte e reconciliacao de ordens continuam
obrigatorios. Uma previsao ou um ganho isolado nao remove esses controles.
