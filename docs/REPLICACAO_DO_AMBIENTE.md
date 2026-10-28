# Replicar o Agente Trader - IA em outro equipamento

Para começar com **banco vazio**, use [Instalação do zero](INSTALACAO_DO_ZERO.md).
O procedimento abaixo trata da migração com preservação dos dados antigos.

Referência registrada em 22/10/2026. O inventário está em
[`config/environment.example.json`](../config/environment.example.json).
Os arquivos `*.example.*` são modelos para consulta: **não são lidos
automaticamente pelo sistema nem provisionam a infraestrutura**.

O nome público é **Agente Trader - IA**. O pacote Python `aurelia_fx`, variáveis
`AURELIA_*` e a identidade técnica da ponte são identificadores de compatibilidade
preservados. Não renomeie esses identificadores ao restaurar: tarefas, imports,
configurações e processos já iniciados dependem deles. O banco, o repositório e
os serviços continuam usando os nomes técnicos `agente_trader`/`agente-trader`.

## 1. O que recuperar

| Origem | Conteúdo necessário |
|---|---|
| GitHub | Código, dependências, scripts, interfaces e catálogo `data/knowledge/` |
| PostgreSQL | Dump consistente do banco inteiro, incluindo todas as tabelas e metadados |
| Windows | `data/models/`, `data/training/`, `Aprendizado/` e configuração Timestral atual |
| Configuração privada | Conexão PostgreSQL de cada máquina e token compartilhado da ponte |
| Modelo promovido | Qualquer diretório adicional referenciado pela configuração ativa |

O dump não contém os pesos, PDFs ou ambientes Python. O Git não contém senhas,
pesos ou resultados binários de treinamento. Preserve também os arquivos de
releases e backups internos de `data/training/`, necessários ao rollback.

Para uma migração definitiva, pause o agente pelo painel, reconcilie posições e
intenções pendentes com o MT5 e interrompa os produtores do projeto antes da
cópia final dos arquivos e do dump. Não mate processos enquanto houver uma
execução pendente. O dump é transacional, mas copiar arquivos durante uma
promoção de modelo pode produzir um conjunto inconsistente.

Na VM atual, o backup é produzido por:

```bash
bash deploy/vm/backup-postgres.sh
```

Leve o `.sql.gz` e seu `.sha256` de `data/database_backups/`. Verifique a soma
antes de restaurar; o arquivo de checksum atual contém o caminho original,
que precisa ser ajustado quando o backup é movido para outra pasta.

## 2. Preparar o Windows

Instale Git, Python compatível e MetaTrader 5. O ambiente operacional registrado
usa Python 3.14.7; as dependências do treinamento foram congeladas para Windows,
Python 3.14 e CPU. Use uma pasta exclusiva do projeto.

```powershell
git clone https://github.com/rsimoes80/agente_trader.git
Set-Location agente_trader
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Restaure os diretórios locais da seção 1. Não copie `.venv`, `.venv-timestral`
ou `.venv-training`: recrie os ambientes no destino. Não transporte arquivos
`.pid`, caches Python nem a calibração `data/mt5_clock_state.json` como se fosse
válida na nova fonte. A normalização precisa se recalibrar no novo ambiente.

### Configurar banco e modelo

Copie `config/database.example.json` para `data/database.json` e preencha host e
senha. Caracteres especiais da senha na URL precisam de percent-encoding.
`AGENTE_TRADER_DATABASE_URL`, se definida, tem prioridade sobre esse arquivo.

Prefira restaurar o `data/timestral.json` atual junto dos respectivos pesos,
ajustando `python`, `cache_dir` e caminhos de releases. Para uma instalação do
modelo original, use `config/timestral.example.json` como ponto de partida.
O exemplo vem com `enabled: false` para não iniciar um modelo incompleto.

```powershell
./install_timestral.ps1
python -m venv .venv-training
.venv-training/Scripts/python.exe -m pip install -r requirements-training-lock.txt
```

O instalador Timestral baixa o modelo e grava a configuração local. Para
recuperar uma versão promovida, preserve sua configuração e seus artefatos:
não substitua a release pela configuração do modelo original. O lock de treino
não garante compatibilidade em outro sistema operacional ou versão de Python.
Dependências de pesquisa e desenvolvimento são opcionais e ficam nos arquivos
`requirements-research.txt` e `requirements-dev.txt`.

Algumas dependências operacionais usam faixas de versões. Para reprodução exata,
guarde no pacote privado de migração a saída de `python -m pip freeze` de cada
ambiente, além da versão do Python e da revisão do SDK. Revise essa saída antes
de compartilhá-la, pois referências de instalação podem conter caminhos locais.

### Configurar MT5 e ponte

Entre no MT5 com a conta demo correta, abra EURUSD e confira o histórico.
Habilite AlgoTrading e a permissão de negociação por Python no terminal.
Credenciais do terminal não são recuperadas pelo dump do PostgreSQL.

Crie `data/mt5_bridge.token` com um token privado. No Linux, o mesmo valor vai
em `deploy/vm/mt5_bridge.env`, seguindo `config/mt5_bridge.example.env`.
O token é entre serviços; não há login do usuário no painel.

A ponte usa `AURELIA_MT5_BRIDGE_HOST` e `AURELIA_MT5_BRIDGE_PORT`; os valores
padrão atuais são `192.168.200.1` e `8769`. Se o IP mudar, configure o ambiente
do usuário da tarefa antes de iniciar e ajuste também o destino no Nginx.
Permita a conexão da VM à porta da ponte no firewall do Windows.

## 3. Preparar o Linux

O Linux precisa de Git, Python com suporte a venv, Docker/Compose e PostgreSQL
16, ou uma versão compatível com o backup. O projeto atual usa o PostgreSQL
em um container existente chamado `postgres`.

**O Compose deste repositório sobe somente o Nginx. Ele não instala PostgreSQL.**
Provisione o banco separadamente com armazenamento persistente e backup. Não
reutilize nem recrie containers de outros projetos.

Clone o Git em uma pasta exclusiva e instale as dependências operacionais:

```bash
git clone https://github.com/rsimoes80/agente_trader.git /CAMINHO/agente-trader
cd /CAMINHO/agente-trader
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Crie o papel `agente_trader_app` com login e senha e uma base vazia
`agente_trader` de sua propriedade. O dump usa `--no-owner --no-acl`: **ele não
recria o papel nem a senha**. Restaure como proprietário da base ou com o papel
adequado, preservando a propriedade e as permissões dos objetos. O usuário da
aplicação não deve ser superusuário.

Exemplo para PostgreSQL instalado diretamente no Linux, com base vazia:

```bash
sudo -u postgres createuser --pwprompt agente_trader_app
sudo -u postgres createdb --owner=agente_trader_app agente_trader
gzip -dc /CAMINHO/backup.sql.gz | psql -h 127.0.0.1 -U agente_trader_app -d agente_trader -v ON_ERROR_STOP=1
```

No container, adapte esses comandos usando `docker exec` e a conexão de
restauração apropriada. Não restaure por cima da base em uso. Configure a
autenticação e o acesso de rede do PostgreSQL para o novo Windows e Linux.
Crie o `data/database.json` da VM com a conexão correspondente; proteja-o com
permissão `0600` e proprietário igual ao usuário do serviço.

### Ajustar a publicação

Antes de instalar os serviços, altere:

- `deploy/vm/agente-trader-diagnostics.service`: `User`, `WorkingDirectory`,
  `ExecStart` e `ReadWritePaths` para o usuário e diretório novos.
- `deploy/vm/nginx-chart.conf`: endereço de `listen` e IP Windows em
  `/api/mt5/chart`. Mantenha o token vindo da variável de ambiente.
- Serviços de backup e estudo de regime em `deploy/vm/`: usuário, caminhos e
  pressupostos do container PostgreSQL. O backup atual usa o nome `postgres`.
- `deploy/vm/mt5_bridge.env`: mesmo token privado do Windows.

Instale o serviço da API usando os arquivos revisados em `deploy/vm/`, execute
`systemctl daemon-reload` e inicie `agente-trader-diagnostics.service`.
Suba o Nginx a partir da raiz do projeto:

```bash
docker compose -p agente-trader -f deploy/vm/docker-compose.yml up -d chart
```

O Compose usa rede do host Linux. A página fica na porta `8097`, a API local
em `8770` e o PostgreSQL em `5432`. A VM precisa alcançar a ponte Windows em
`8769`. A configuração não inclui HTTPS nem publicação na internet.

Instale também os timers de backup e, se estiver dando continuidade ao estudo
existente, o serviço/timer `agente-trader-regime-study`, após revisar seus
caminhos. Não reinstale esses serviços com caminhos do usuário antigo.

## 4. Ativar uma única instância

Para reproduzir a execução coordenada de EURUSD/XAUUSD, copie
`config/multi_asset.example.json` para `data/multi_asset.json` no Windows antes
de iniciar o agente. A seleção e os lotes vêm do PostgreSQL restaurado. Perfis e
autorizações são vinculados à conta e ao contrato; trocar de conta exige nova
conferência. Consulte [múltiplos ativos](MULTIPLOS_ATIVOS.md).

Uma cópia do banco pode conter uma sessão com estado desejado `running`.
Antes de instalar os agendamentos, confirme o estado restaurado e desative as
tarefas do equipamento antigo. Não use dois bancos clonados para controlar a
mesma conta MT5 simultaneamente.

Somente depois de preparar banco, modelos, ponte e MT5, execute no Windows:

```powershell
./install_mt5_bridge_startup.ps1
./install_agent_startup.ps1
./install_training_startup.ps1
```

Os instaladores registram tarefas com gatilhos automáticos; agente e ponte
também são iniciados pelos scripts. Não é preciso instalar os coletores
opcionais `History` e `Timestral` para operar o agente principal.

## 5. Conferir antes de retomar

- Commit restaurado identificado e modelos ativos presentes com hashes válidos.
- PostgreSQL acessível pelas duas máquinas, com histórico e memória preservados.
- MT5 demo correto, posições e intenções reconciliadas, sem ordens de teste forçadas.
- Gráfico com candles atuais e relógio UTC normalizado.
- Agente e laboratório disponíveis no painel, sem outra instância operacional.
- `/`, `/mercado`, `/diagnostico` e `/treinamento` acessíveis na nova VM.
- Backup executável e arquivos locais dos modelos incluídos na política de cópia.

O treinamento por ativo também requer a pasta `data/training`, incluindo datasets,
checkpoints, releases e `active/<symbol>/<profile_id>.json`. O GitHub não contém
os pesos ajustados. Consulte [treinamento por ativo](TREINAMENTO_POR_ATIVO.md).

Uma mudança de conta, fonte ou modelo pode exigir novo preparo e contexto;
preservar o banco não garante retomar qualquer sessão em outra conta.

Não envie configurações preenchidas ou backups ao GitHub. Os modelos versionados
em `config/` contêm somente exemplos e informações técnicas públicas.
