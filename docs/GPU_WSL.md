# GPU no Ubuntu WSL do agente trader

## Hardware e diagnóstico

O diagnóstico fora do sandbox confirmou uma NVIDIA GeForce GTX 1050 Ti,
4 GiB de VRAM, capacidade CUDA 6.1, driver Windows 581.42 e `/dev/dxg` exposto
no WSL. Não foi necessário atualizar o driver ou reinstalar o WSL.
A Intel UHD 630 usa RAM compartilhada; os 11,9 GiB mostrados para ela no
Gerenciador de Tarefas não são VRAM dedicada adicional.

O teste dentro do sandbox do Codex inicialmente mostrou GPU bloqueada pelo
sistema operacional. O mesmo teste no host Ubuntu funcionou. Essa restrição do
sandbox não deve ser diagnosticada como ausência de GPU no WSL.

Referência: [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/).
O WSL utiliza o driver NVIDIA do Windows; não instalar um driver Linux NVIDIA
por cima dessa integração.

## Configuração aplicada

O leitor Qwen3-4B usa o runtime oficial llama.cpp **b11962, CUDA 12.8**, com:

- 24 camadas enviadas para CUDA0; o restante permanece na CPU;
- contexto 8192, um slot e requisições serializadas;
- batch 256, microbatch 64 e duas threads de CPU;
- limites existentes de 5 GiB de RAM, 256 MiB de swap e CPU equivalente a dois núcleos.

CUDA 12 foi escolhido para preservar compatibilidade com a arquitetura Pascal.
O binário oficial foi inspecionado quanto ao conjunto de arquiteturas e validado
por detecção de dispositivo e inferência real; não basta a biblioteca detectar
uma GPU. Os dois arquivos oficiais têm hashes fixos no instalador.

O drop-in `zz-cuda.conf` substitui apenas o comando do serviço e o caminho de
bibliotecas. `resource-limits.conf` continua impondo os limites de memória/CPU.
Não há mudança nas estratégias, nos pesos dos modelos ou no estado de negociação.

O Timestral continua em CPU. A instalação existente é PyTorch 2.15.0+cpu;
trocá-la por um pacote CUDA genérico não resolve a compatibilidade Pascal e a
VRAM de 4 GiB não comporta presumidamente todos os modelos simultâneos. O primeiro
orçamento de GPU foi atribuído ao leitor, responsável pela maior pressão de RAM.
O treinamento não foi ativado por essa configuração.

## Evidências e limites

Na primeira inferência curta (19 tokens de entrada e 3 de saída), o servidor
respondeu `OK.` em aproximadamente 5,57 segundos. O monitor registrou atividade
da GPU e consumo total próximo de 3046 MiB, incluindo o uso do Windows, deixando
cerca de 959 MiB livres. A memória do serviço ficou próxima de 1,65 GiB e o Ubuntu
apresentou 8,3 GiB disponíveis naquele instante.

Esses números são de um teste curto, não um benchmark de análise completa.
Contextos grandes, outros programas Windows e outros modelos podem aumentar o
consumo e a latência. Não há promessa de eliminar todos os gargalos. O limite de
RAM anterior continua necessário, e não se deve preencher os 4 GiB sem reservar
espaço para o sistema gráfico.

## Instalar ou reproduzir

Execute no terminal normal do Ubuntu, com acesso a GPU e à rede:

```bash
.venv/bin/python install_literature_cuda.py --layers 24
```

O instalador baixa e verifica os dois assets oficiais, instala-os isoladamente
em `.tools/llama-cuda12/`, testa `--list-devices`, instala os drop-ins e reinicia
somente o servidor textual. Não instala CUDA Toolkit completo nem driver Linux.
As tarefas de leitura devem ser interrompidas antes de reconfigurar um servidor
em uso e retomadas após a validação; reiniciar inferência invalida chamadas em curso.

Validar:

```bash
/usr/lib/wsl/lib/nvidia-smi
curl --fail http://127.0.0.1:8791/health
systemctl --user show agente-trader-literature-model.service -p MemoryCurrent -p MemoryPeak -p MemoryMax
journalctl --user -u agente-trader-literature-model.service -n 20 --no-pager -o cat
```

Além do health check, faça uma chamada curta ao endpoint de completions e monitore
`nvidia-smi` para confirmar execução. O gráfico 3D da Intel no Gerenciador de
Tarefas não mede o trabalho CUDA da NVIDIA. Para acompanhar no Ubuntu:

```bash
watch -n 2 /usr/lib/wsl/lib/nvidia-smi
```

O perfil aplicado fica em `data/references_cache/literature-runtime.json`.
Relatórios novos dos especialistas incluem esse perfil na especificação do modelo
e no identificador da rodada; páginas novas do currículo registram o runtime.
A mudança de backend não torna as fichas semanticamente revisadas ou aprovadas.

## Voltar para CPU

Se o backend CUDA falhar ou outros programas precisarem da VRAM:

1. Pare os workers de pesquisa e o servidor textual.
2. Remova somente o drop-in `zz-cuda.conf` e o arquivo privado
   `data/references_cache/literature-runtime.json`.
3. Execute `systemctl --user daemon-reload` e inicie o servidor textual.
4. Confirme health/inferência antes de retomar os workers.

O comando CPU e os limites permanecem no drop-in de recursos. Essa operação não
requer apagar modelos, reconstruir o banco, alterar o MT5 ou retomar negociação.
