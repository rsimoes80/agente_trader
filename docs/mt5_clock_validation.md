# Validação do relógio MT5 — 20/10/2026

Implementação: `d90095b`.

- Suíte completa: **95 testes passaram** (`unittest discover -s tests -q`).
- Ruff: imports e regras E4/E7/E9/F verificados nos módulos alterados.
- Os dois scripts PowerShell passaram pela análise sintática do PowerShell.
- Tarefa Windows `AgenteTrader-MT5Bridge`: registrada, em execução, com gatilho no logon.
- Serviço Linux `agente-trader-diagnostics`: habilitado e ativo.
- Às 11:30 UTC, o último candle M5 retornado era 11:30 UTC, com tick cerca
  de 2 segundos atrás. Antes da correção, a diferença era aproximadamente 10.800 segundos.
- Perfil confirmado: `thinkmarkets-ny-close-v1`, `broker_wall`, deslocamento
  de 10.800 segundos nesta data, contrato `mt5-utc-v1`.
- Encerramento controlado apenas do processo da ponte: supervisor iniciou novo
  PID e a API voltou com UTC correto, usando o cache persistente.
- Reinício real do serviço Linux: observador voltou a `observing`, `source_status=ok`.
  O checkpoint anterior foi retomado: uma gravação e um candle distinto; sem
  duplicação do último candle durante esses reinícios.
- Nova captura: 1.500 candles fechados. Desenvolvimento UTC:
  `9c5936a6-6963-43d1-9897-32c4a919e9de` (900 barras).
  Plano `validation-0a28c29f-01e4-4b89-bf79-47bcdbc725ce`.
  Holdout reservado, não avaliado; nenhuma estratégia promovida.
- Backup PostgreSQL concluído após a validação.

Fechar/reabrir o MT5 foi coberto com simulação do SDK; o terminal real não foi
fechado. Nenhuma ordem foi enviada.

## Limite observado na infraestrutura

Windows e VM concordavam em aproximadamente um segundo. O NTP/Chrony da VM está
ativo, mas suas fontes externas apareciam inacessíveis e não sincronizadas.
A proteção entre os relógios foi validada: divergência acima de 60 segundos
interrompe novas observações em vez de aceitar timestamps incorretos. A
conectividade NTP externa da VM ainda precisa ser restabelecida na infraestrutura.

A tarefa Windows opera após logon do usuário. O MT5 deve permanecer aberto e
conectado; durante indisponibilidade, o agente aguarda e tenta novamente.
