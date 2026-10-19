# PostgreSQL do agente

O repositório compartilhado de dados fica na VM `192.168.97.221`, porta `5432`,
banco `agente_trader`, schema `public`, usuário exclusivo `agente_trader_app`.
O PostgreSQL 16 existente roda no container `postgres`; outros bancos permanecem separados.
As credenciais ficam fora do Git em `data/database.json`, com modo 0600 na VM.
`AGENTE_TRADER_DATABASE_URL` tem prioridade sobre esse arquivo.

## Aplicação

Instale `pip install -r requirements-replay.txt` (ou `requirements.txt` no painel Windows).
`python run_replay.py --csv CAMINHO.csv --timeframe M5` usa PostgreSQL por padrão.
`--db CAMINHO.sqlite3` seleciona explicitamente uma memória offline isolada.
Configuração ausente ou indisponibilidade não troca silenciosamente para SQLite.
O monitor Dukascopy grava candles fechados, snapshots e evidências antes de publicar a leitura.
Replay grava decisões, experiências, hipóteses, expectativas, execução simulada e evidências.
Candles e versões do catálogo são preservados em `project_records` com hash.
Os JSON de conhecimento no Git continuam a fonte revisável das regras; sincronizar versões
ao banco não muda aprovação, validação ou estratégia. PDFs continuam em `Aprendizado`.

O backend PostgreSQL compartilha os contratos do journal. Pool limitado a quatro conexões,
transações por observação e triggers impedindo UPDATE, DELETE e TRUNCATE preservam o histórico.
Payloads ficam como texto canônico para preservar hashes; consultas podem usar `payload_json::jsonb`.
O schema do journal permanece 3. A criação de tabelas na inicialização é serializada no banco.

## Migração e recuperação

`python migrate_memory.py` primeiro faz um backup consistente do SQLite e copia os registros
em uma transação PostgreSQL. IDs existentes com hashes iguais são ignorados; divergência
de hash interrompe a importação. O SQLite original não é apagado. Relatórios e cópias ficam
em `data/database_backups/`, fora do Git. Só migre origens confiáveis de schema 3.

Na VM, `bash deploy/vm/backup-postgres.sh` cria dump comprimido apenas deste banco.
Não há exclusão automática de backups. Para restaurar, use outra base vazia e o administrador;
não sobrescreva o journal em uso. O armazenamento do container PostgreSQL é administrado
pelo servidor existente e não foi recriado por este projeto.

## DBeaver

Driver PostgreSQL, host/porta/banco/usuário acima; senha fornecida separadamente.
O servidor existente está com SSL desativado. A conexão direta depende da rede local;
para conexão por túnel SSH, use `rafael@192.168.97.221`, porta SSH 22,
e destino do banco `127.0.0.1:5432`. Não houve abertura de nova porta de rede.

Credenciais administrativas não são usadas pela aplicação. O usuário do projeto não é
superusuário e não pode criar bancos ou papéis. Alterações no journal devem ocorrer por
novos eventos, sem editar as linhas existentes pelo DBeaver.

Referência do driver: [pool e transações Psycopg](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).

## Consultas V4 no DBeaver

As views `public.market_regime_history` e `public.experience_regime_history` expõem os novos campos. Registros anteriores não recebem regime retroativo. As versões do catálogo ficam em `project_records`.
