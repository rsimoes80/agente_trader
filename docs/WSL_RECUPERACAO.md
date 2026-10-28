# Recuperar o WSL quando o Maestri não lista as distribuições

Diagnóstico nesta sessão: Ubuntu ativo, modelo textual com cerca de 9 GiB RSS,
RAM livre perto de 111 MiB e swap de 3 GiB praticamente esgotado. Após encerrar
somente a pesquisa dos livros, a memória disponível subiu para aproximadamente
9,4 GiB. Mesmo assim, wsl.exe, cmd.exe e PowerShell chamados de dentro do Ubuntu
não responderam aos testes de 8–12 segundos. Isso separa a pressão de recursos
da falha de comunicação com o Windows; não comprova a causa exata dessa falha.

O modelo agora tem um drop-in de limites em
`~/.config/systemd/user/agente-trader-literature-model.service.d/resource-limits.conf`,
cuja fonte está em `deploy/linux/literature-model-resource-limits.conf`:
memória máxima 5 GiB, swap máximo 256 MiB, CPU equivalente a dois núcleos,
batches menores e prazo de parada de dez segundos. O contexto continua em 8192.
O teste de inicialização com essa configuração respondeu health=ok, com pico
inicial de aproximadamente 4 GiB; esse teste não mede uma análise longa completa.
Não ampliar automaticamente os limites se o modelo não couber: mantenha a
pesquisa parada e revise sua configuração. Os serviços de pesquisa não precisam
estar ativos para usar os terminais Codex no Maestri.

## Recuperação no Windows

1. Salve os arquivos do IDE. Feche o Maestri e as janelas conectadas ao Ubuntu.
2. Abra **Windows PowerShell** pelo menu Iniciar do Windows, fora do Ubuntu.
3. Execute `wsl --shutdown`. Isso encerra as distribuições WSL e interrompe os
   serviços Linux; não apaga os arquivos nem o banco persistente.
4. Execute `wsl --list --verbose`. Deve aparecer a distribuição Ubuntu.
5. Se o comando também travar, abra PowerShell **como Administrador** e execute:

   ```powershell
   Get-Service WslService,LxssManager -ErrorAction SilentlyContinue | Restart-Service -Force
   ```

   Em seguida, repita `wsl --list --verbose`. Se o reinício do serviço falhar
   ou a listagem continuar travando, reinicie o Windows e repita a consulta.
6. Inicie o Ubuntu com `wsl -d Ubuntu -u rafael` e reabra o Maestri.
7. No Maestri, configure WSL, Ubuntu, usuário rafael e o comando absoluto
   `/home/rafael/.local/bin/codex --no-daemon`, conforme o guia de orquestração.

A enumeração do WSL precisa funcionar no PowerShell antes de atribuir o problema
ao campo Distribuição do Maestri. Se a consulta do PowerShell responder e a tela
continuar com erro, reabra a janela de edição e, se necessário, reinicie o Maestri.
Não reinstale o Ubuntu nem remova a distribuição para corrigir esse timeout.

## Conferir os serviços após a recuperação

```bash
free -h
systemctl --user status agente-trader-agent.service agente-trader-observation.service --no-pager
systemctl --user show agente-trader-literature-model.service -p MemoryHigh -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec
```

A recuperação de infraestrutura não autoriza START ou RESUME de negociação.
O estado operacional deve ser conferido no painel após a reconexão.

A aceleração CUDA foi configurada posteriormente para o leitor; consulte
[GPU_WSL.md](GPU_WSL.md). Os limites de memória continuam válidos também com GPU.
