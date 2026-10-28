# Instalar do zero em outro ambiente

Este procedimento prepara um banco novo e persistente, sem restaurar o banco
antigo. O repositório fornece código, catálogo, requisitos, configuração de
infraestrutura e gerador dos arquivos privados. Modelos são baixados novamente.
Não copie ambientes virtuais, calibração de relógio, arquivos PID ou credenciais
do equipamento anterior. Dados históricos e resultados serão coletados novamente.

## 1. Instruções para o Codex

Leia `AGENTS.md`, este guia e `config/new-environment.example.json`.
Use clones novos em diretórios exclusivos nas duas máquinas. Descubra IPs
privados alcançáveis entre elas e confirme as portas livres antes de provisionar.
Execute os comandos na máquina indicada. Nunca rode o gerador no clone de
produção atual: ele recusa substituir configurações existentes.

Pré-requisitos de sistema que o Codex deve instalar/verificar:

| Máquina | Requisitos |
|---|---|
| Linux x86-64 | Git, Python 3 para gerar configuração, Docker Engine com Compose v2 e serviço habilitado no boot |
| Windows x86-64 | Git, Python 3.14 x64 com pip/venv, PowerShell, MetaTrader 5 da corretora |

No Linux instale Docker e o plugin Compose pelo procedimento adequado à
distribuição. Valide `git --version`, `python3 --version`, `docker version` e
`docker compose version`. O usuário que executa Compose precisa acessar o daemon.
Os containers instalam Python 3.14 e requisitos operacionais automaticamente.
No Windows valide `git --version` e `python --version` antes de continuar.
Instalações do sistema podem exigir privilégios administrativos.

Use rede privada/VPN: o painel controla o agente e não tem autenticação de
usuário nem TLS. Restrinja o painel aos operadores, PostgreSQL ao Windows e
ao próprio Linux, e a ponte Windows ao Linux. Não exponha essas portas à
internet. Revise também as regras de publicação do Docker no firewall.

## 2. Linux: gerar e subir infraestrutura

```bash
git clone https://github.com/rsimoes80/agente_trader.git
cd agente_trader
cp config/new-environment.example.json config/new-environment.local.json
```

Edite `linux_ip` e `windows_ip` com os endereços privados reais. As portas
padrão são painel 8097, PostgreSQL 5432 e ponte Windows 8769. A API usa
127.0.0.1:8770 fixo. Ajuste as portas no JSON se houver conflitos; para conflito
na 8770 use outro servidor. Deixe as três credenciais vazias: o gerador cria
valores aleatórios e os salva no arquivo privado, com permissão 0600 no Linux.

```bash
python3 setup_environment.py --role linux
docker compose -f data/provisioning/compose.json config --quiet
docker compose -f data/provisioning/compose.json up -d --build
docker compose -f data/provisioning/compose.json ps
curl --fail http://127.0.0.1:8770/health
```

O Compose novo é independente do antigo `deploy/vm/docker-compose.yml`:
cria PostgreSQL 16 com volume `agente-trader-fresh_postgres-data`, usuário
administrador separado, papel de aplicação sem superusuário, API e Nginx.
O SQL de bootstrap só roda em volume novo. A aplicação cria seu schema e
sincroniza `data/knowledge/` na primeira inicialização; não execute
`migrate_memory.py` nem restaure dumps. O banco não terá histórico de mercado.

API e Nginx usam rede do host Linux. Os caminhos absolutos são gerados para
este clone. Não mova a pasta depois de configurar. Os serviços reiniciam
automaticamente com Docker. O estado do banco permanece no volume; arquivos
da aplicação permanecem em `data/`. Não execute `docker compose down -v`.

Se falhar, use `docker compose -f data/provisioning/compose.json logs --tail 100`.
Não tente corrigir falha de senha apagando o volume: verifique se o projeto
Compose/volume já existia e preserve seus dados. Mudanças posteriores nas
senhas do JSON não alteram usuários de banco já inicializado.

## 3. Windows: configurar os mesmos dados privados

Clone o mesmo commit do Linux e transfira por canal privado o arquivo
`config/new-environment.local.json` gerado no Linux para a mesma posição
relativa no Windows. Ele contém senhas: não cole em issues, commits ou logs.
Restrinja acesso ao usuário que executará as tarefas.

```powershell
git clone https://github.com/rsimoes80/agente_trader.git
Set-Location agente_trader
python setup_environment.py --role windows
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip check

$newEnvironment = Get-Content config/new-environment.local.json -Raw | ConvertFrom-Json
[Environment]::SetEnvironmentVariable('AURELIA_MT5_BRIDGE_HOST', $newEnvironment.windows_ip, 'User')
[Environment]::SetEnvironmentVariable('AURELIA_MT5_BRIDGE_PORT', [string]$newEnvironment.bridge_port, 'User')
$env:AURELIA_MT5_BRIDGE_HOST = $newEnvironment.windows_ip
$env:AURELIA_MT5_BRIDGE_PORT = [string]$newEnvironment.bridge_port
```

O gerador cria `data/database.json`, `data/mt5_bridge.token`,
`data/multi_asset.json` e `data/timestral.json` com caminhos deste clone.
Remova/corrija variáveis antigas `AGENTE_TRADER_DATABASE_URL` e `TIMESTRAL_*`
do usuário/processo se existirem: elas têm prioridade sobre os arquivos.
Confira também o ambiente herdado pelo Agendador; se necessário encerre e
reabra a sessão Windows antes de instalar as tarefas.

## 4. Windows: modelos e treinamento

```powershell
./install_timestral.ps1
.venv-timestral/Scripts/python.exe -m pip check
python -m venv .venv-training
.venv-training/Scripts/python.exe -m pip install -r requirements-training-lock.txt
.venv-training/Scripts/python.exe -m pip check
.venv-training/Scripts/python.exe -c "import sys; from pathlib import Path; sys.path.insert(0,'src'); from aurelia_fx.training.proof import prepare; prepare(Path.cwd())"
```

O instalador baixa o Timestral-209M original na revisão fixada pelo exemplo,
e o último comando baixa o Timestral-5M usado pelo laboratório. Internet é
necessária para pip, GitHub, Hugging Face e o índice CPU do PyTorch. Não há
necessidade de copiar pesos treinados antigos. O SDK está fixado por commit
em `requirements-timestral.txt`; o lock do treinamento corresponde a Windows
CPU/Python 3.14. Não instale esses requisitos no ambiente operacional.
Se um pacote não tiver distribuição compatível, registre a falha e resolva a
compatibilidade antes de prosseguir; não ignore erros de pip.

Depois de concluir os downloads e verificar imports, habilite o modelo:

```powershell
.venv/Scripts/python.exe -c "import json; from pathlib import Path; p=Path('data/timestral.json'); c=json.loads(p.read_text()); c['enabled']=True; p.write_text(json.dumps(c,indent=2),encoding='utf-8')"
.venv-timestral/Scripts/python.exe -c "import torch, timestral, huggingface_hub; print('Imports Timestral OK')"
```

Pesquisa/replay e desenvolvimento possuem requisitos adicionais nos arquivos
`requirements-research.txt`, `requirements-replay.txt`, `requirements-dev.txt`.
São opcionais para o serviço operacional; instale em ambientes separados caso
esse trabalho seja solicitado. `Aprendizado/` contém materiais externos fora
do Git e não é necessário para o bootstrap do catálogo versionado.

## 5. MT5, firewall e inicialização

Abra MT5 na sessão Windows do usuário das tarefas, entre na conta **demo**
da nova corretora, habilite AlgoTrading e permita negociação via Python.
A autenticação no terminal precisa ser fornecida pelo operador. Verifique os
nomes dos símbolos disponíveis nessa conta; cadastre os ativos pelo painel.
Uma conta/contrato novo requer configuração própria, sem copiar autorizações
do banco antigo. Windows deve permanecer com sessão interativa disponível.

Libere TCP da ponte somente para o IP Linux no firewall Windows. Exemplo em
PowerShell elevado, após carregar `$newEnvironment` como na seção 3:

```powershell
New-NetFirewallRule -DisplayName 'AgenteTrader ponte privada' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $newEnvironment.windows_ip -LocalPort $newEnvironment.bridge_port -RemoteAddress $newEnvironment.linux_ip
```

Teste banco e inicialize tarefas no PowerShell do usuário operacional:

```powershell
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); from aurelia_fx.storage import open_memory; m=open_memory(); m.close(); print('Banco e catalogo OK')"
New-Item -ItemType Directory -Force data/training | Out-Null
./install_mt5_bridge_startup.ps1
./install_agent_startup.ps1
./install_training_startup.ps1
Get-ScheduledTask -TaskName 'AgenteTrader-*' | Select-Object TaskName,State
```

Agente e ponte são iniciados pelos instaladores. O laboratório usa gatilho de
logon e verificação recorrente. Não instale coletores History/Timestral ou
observadores de pesquisa em paralelo: não são necessários ao ciclo principal.
O estado inicial sem sessão deve permanecer parado; iniciar negociação demo
é uma ação posterior do operador no painel.

## 6. Aceite no destino e operação

Confirme no Linux `/health` com `ok: true` e acesso do navegador a
`http://IP_LINUX:PORTA_WEB/`, `/mercado`, `/diagnostico` e `/treinamento`.
Confirme gráfico com candles atuais, consulta do contrato pelo painel e
operações de configuração sem erro 403 (origem configurada para o novo IP).
Cheque heartbeat do worker, conexão do treinamento e ausência de erros de
modelo/MT5/banco nos logs. Não envie ordens para testar instalação.
Reinicie o Docker e faça novo logon Windows para conferir recuperação das
rotinas. Documente commit instalado, versões de Python e `pip freeze` dos
três ambientes fora do Git. Histórico insuficiente logo após instalação é
esperado: a coleta e o aquecimento serão refeitos pelo agente.

Antes de usar continuamente, configure backup do volume PostgreSQL e dos
modelos/arquivos locais. Exemplo de dump sem publicar credenciais:

```bash
mkdir -p data/database_backups
docker compose -f data/provisioning/compose.json exec -T db pg_dump -U postgres -d agente_trader --no-owner --no-acl | gzip > data/database_backups/agente-trader.sql.gz
```

Use nome de backup com data na rotina definitiva, valide o retorno de ambos
os comandos (`set -o pipefail` no Bash) e copie para armazenamento externo.
O script antigo de backup em `deploy/vm/` depende do container `postgres` do
servidor anterior; não o instale sem adaptar para este Compose.

Todos os arquivos preenchidos e gerados são ignorados pelo Git. O gerador
não instala pacotes do sistema, não inicia serviços e não apaga dados; execute
os comandos acima e registre pendências para concluir o ambiente. O exemplo
versionado nunca deve conter credenciais reais.
