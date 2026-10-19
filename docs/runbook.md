# Runbook inicial

## Replay integrado EUR/USD

Execute `python run_replay.py --capture-mt5 --count 1500 --validate-temporal` para capturar candles fechados, avaliar desenvolvimento/validação e reservar os 20% finais. Para um replay completo offline, use `python run_replay.py --csv CAMINHO.csv --timeframe M5 --source FONTE`. O banco padrão fica em `data/agent_memory.sqlite3` (schema 2, migração aditiva); cada execução gera HTML, JSON, decisões, execuções simuladas, equity e manifesto em `data/replays/`. Consulte [replay.md](replay.md) e [execution_simulation.md](execution_simulation.md) para requisitos do CSV, custos, resultado em R, hipóteses de execução e partições temporais.

## Aplicação local

No Windows, instalar dependências conforme `requirements.txt` no `.venv` existente e iniciar `python app.py`. A UI local escuta em `127.0.0.1:8768`. O modo continua `paper`; o feed FIX é leitura. Credenciais usam DPAPI do usuário atual.

## MT5 e gráfico publicado

O gráfico em `http://192.168.97.221:8097/` depende de terminal MT5 conectado no Windows, ponte `mt5_bridge.py` e container/proxy Nginx da VM. Reinicie a ponte com `run_mt5_bridge.ps1`. O token de ponte é segredo; não copiar logs/env para tickets. Health-check e rotação de token devem ser formalizados.

## Auditoria e pesquisa

1. Confirmar fonte, símbolo, timezone UTC, timeframe e qualidade do histórico.
2. Executar replay/backtest com dataset identificado e custo declarado.
3. Guardar configuração/hash e métricas por período; não treinar com a janela final.
4. Relatar ausência de trades e insuficiência de amostra como resultado válido.
5. Nenhum candidato autoriza ordem. Parar feed/servidor pelo processo operacional conhecido se houver comportamento inesperado.

## Estados de falha

Dados inconsistentes/atrasados, spread fora da regra, perda/drawdown acima do limite, segredo inválido, sessão desconectada ou journal indisponível devem resultar em bloqueio (`NO_TRADE`/`RISK_LOCK`), log redigido e sem retry que duplique ação. Ainda faltam alertas, persistência transacional e kill switch de executor porque não há executor.

## Ambiente Linux

DPAPI não é portátil para Linux. Para mover o painel/feed ou segredos para a VM, desenhar primeiro armazenamento de segredos adequado e política de acesso; não reutilizar o ciphertext local. O serviço MT5 atual é Windows-only.
