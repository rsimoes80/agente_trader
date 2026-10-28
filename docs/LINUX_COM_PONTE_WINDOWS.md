# Agente e treinamento no Linux, terminal MT5 no Windows

Esta topologia mantém banco, painel, estratégia, risco, modelos e treinamento
no Linux. Somente o adaptador de acesso ao terminal MT5 executa no Windows.
A ponte fornece candles, contratos, cotações e reconciliação, além de encaminhar
as ordens já decididas pelo Linux. O MT5 oficial requer Windows.

## Linux

Instale a infraestrutura com banco vazio conforme as seções 1 e 2 de
`INSTALACAO_DO_ZERO.md`. Preserve o volume existente nas tentativas seguintes.
Crie `.venv`, `.venv-timestral` e `.venv-training` com Python 3.14:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
python3 -m venv .venv-timestral
.venv-timestral/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-timestral/bin/python -m pip install -r requirements-timestral.txt
python3 -m venv .venv-training
.venv-training/bin/python -m pip install -r requirements-training-lock.txt
```

O lock de treinamento foi validado também em Linux x86-64/Python 3.14/CPU.
Crie `data/timestral.json` a partir de `config/timestral.example.json`, com
`python` apontando para o caminho absoluto `.venv-timestral/bin/python`, e
`cache_dir` apontando para `data/models/timestral` deste clone. Mantenha
`enabled=false` até concluir downloads e imports.

```bash
.venv-timestral/bin/python install_timestral_model.py
.venv-training/bin/python run_training_proof.py --prepare
.venv-training/bin/python run_training_proof.py
.venv/bin/python -m pip check
.venv-timestral/bin/python -m pip check
.venv-training/bin/python -m pip check
```

Habilite `enabled` no JSON após verificar o carregamento local do 209M.
O teste 5M usa dados sintéticos, sem validar rentabilidade ou enviar ordens.

```bash
python3 install_linux_workers.py
loginctl enable-linger "$USER"
systemctl --user status agente-trader-agent.service
systemctl --user list-timers agente-trader-training.timer
```

O instalador usa a configuração privada já gerada, prepara o token local e
instala unidades systemd do usuário. Ele não inicia uma sessão de negociação.
O timer verifica a fila de treinamento a cada minuto, sem executar dois jobs
da mesma unidade simultaneamente. Linger permite iniciar o gerenciador do
usuário no boot; pode exigir privilégios conforme a política do sistema.

### Política de daytrade

Com as sessões paradas e sem exposição, configure a política de direção H1:

```bash
python3 install_linux_workers.py --history --entry-policy daytrade-h1-confirmed-v1
systemctl --user restart agente-trader-agent.service
docker compose -f data/provisioning/compose.json up -d --build api
```

O instalador recusa mudar a política com sessão ativa ou exposição pendente.
Ele persiste `entry_policy` no JSON privado e o ambiente dos serviços, além de
atualizar o ambiente da API no Compose gerado. O serviço de treinamento recebe
a mesma identidade. Scripts CLI isolados usam a política estrita por padrão;
para reproduzir a política configurada, prefixe o comando com
`AURELIA_ENTRY_POLICY=daytrade-h1-confirmed-v1`. A importação recusa valores
desconhecidos. A configuração da API é aplicada ao recriar seu container.

Nesta política, H1 precisa estar confirmado em alta para compras ou em baixa
para vendas. H4/D1, regime e divergências continuam como contexto e features,
sem vetos adicionais de regime ou confirmação macro. O gatilho de pullback,
dados válidos, spread, stop, custos e limites de risco permanecem exigidos.
Limites de horário e fechamento da sessão continuam aplicados. A mudança gera
outra identidade de estratégia e de aprendizado; não converte estatísticas
antigas em evidência da política nova. Não inicia negociação automaticamente.

As hipóteses `trend-only-h4-h1-confirmed-v1` (original) e
`daytrade-h1-continuation-v1` (gatilho de continuação mais flexível) são
reproduzíveis e podem ser comparadas offline com `run_operational_audit.py
--compare-daytrade`. Veja a comparação em `FLEXIBILIZACAO_DAYTRADE_H1.md`.

Para coletar e validar inicialmente 30 dias de EURUSD sem iniciar negociação:

```bash
AURELIA_MT5_BRIDGE_URL=http://IP_WINDOWS:PORTA_PONTE .venv/bin/python run_history.py --days 30 --full
python3 install_linux_workers.py --history
systemctl --user status agente-trader-history.timer
```

Substitua o endereço da primeira linha pelos valores privados reais. A opção
`--history` instala uma atualização incremental a cada 15 minutos. Cada execução
verifica se a sessão está parada antes da coleta; durante uma sessão ativa,
delega a coleta ao ciclo principal. O relatório de cobertura fica no PostgreSQL
e em `journalctl --user -u agente-trader-history.service`. Não substitua lacunas
por candles sintéticos nem confunda cobertura aprovada com estratégia validada.

## Windows: somente a ponte

Use um clone exclusivo do mesmo commit Linux, Python 3.14 x64 e MT5 aberto
na sessão interativa do usuário. Não instale tarefas de agente ou treinamento.

```powershell
py -3.14 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-bridge.txt
.venv/Scripts/python.exe -m pip check
```

Por canal privado, copie **somente** `bridge_token` da configuração Linux para
`data/mt5_bridge.token` (texto), e crie `data/mt5_bridge.env` como JSON com
`linux_ip`, `windows_ip` e `bridge_port`. Não copie senhas do PostgreSQL ou modelos.
Restrinja as ACLs desses dois arquivos ao usuário da ponte e SYSTEM.
`run_mt5_bridge.ps1` lê esses arquivos a cada inicialização. Libere a porta
TCP no firewall Windows somente para o IP Linux, conforme o guia original.

```powershell
./install_mt5_bridge_startup.ps1
Get-ScheduledTask -TaskName AgenteTrader-MT5Bridge
```

A tarefa existente de outro clone é preservada: o instalador recusa substituí-la.
No WSL, os endereços privados podem mudar após reiniciar o Windows; se mudarem,
atualize a configuração privada, as unidades Linux, o Nginx e o firewall.

## Verificação e limites

Confirme `/health` da API e da ponte, consultas de contrato e candles através
do painel, heartbeat do worker e execução do timer. Mantenha a sessão parada.
Não envie ordens para validar instalação. Confirme retorno após reiniciar os
serviços e, posteriormente, após novo logon Windows/reinício do Docker.

A rota POST `/api/mt5/rpc` exige token e endereço Linux permitido no Windows;
o Nginx bloqueia essa rota no painel. As operações SDK são enumeradas em uma
lista explícita. O envio recusa contas reais, troca de conta/terminal e negociação
desabilitada. A ponte persiste o identificador antes de chamar o SDK e recusa
reenvios. Uma falha de rede deixa resultado incerto para reconciliação pelo
journal Linux: não remova o journal Windows `data/bridge-sends.sqlite3`.
Inclua ambos os journals nos backups. A ponte não decide entradas nem treina.

Continue aplicando o backup, controle de acesso à rede privada e verificações
de aceite do guia original. Não publique arquivos privados, dumps ou modelos.

## Observação ao vivo sem ordens

O instalador aceita `--observe` para habilitar o serviço independente
`agente-trader-observation.service`. Ele aquece contexto e verifica inferência,
mas usa um cliente de ponte restrito a consultas e não inicia negociação.
Consulte `TESTES_AO_VIVO_SEM_ORDENS.md` para instalação, diagnóstico, regras
verificadas de encerramento e testes de falha. Use o caminho literal do Python
na venv Timestral; resolver seu symlink perde o ambiente de dependências.
