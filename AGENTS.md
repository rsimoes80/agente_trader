# Instalação em outro ambiente

Quando a tarefa for instalar, replicar ou configurar este projeto em outro
servidor, leia primeiro `docs/INSTALACAO_DO_ZERO.md` e
`config/new-environment.example.json`. Siga o procedimento até a verificação
final e informe o que não pôde ser verificado no servidor de destino.

O usuário autoriza começar com banco vazio e baixar os modelos públicos
originais. Não é necessário recuperar dados ou pesos treinados do equipamento
anterior. Não apague bancos ou volumes existentes para obter esse resultado:
use instalação isolada. O fluxo antigo em `docs/REPLICACAO_DO_AMBIENTE.md`
é para preservar dados; para instalação nova prevalece o guia do zero.

Linux hospeda PostgreSQL/API/Nginx; Windows com sessão interativa e MT5 demo
hospeda agente, ponte e treinamento. Linux sozinho não substitui o MT5.
Não reutilize os IPs/caminhos históricos do README como destino novo.
Peça somente os dados ausentes: IPs privados das duas máquinas e acesso à
conta demo no terminal. Gere senhas e token com `setup_environment.py`.
Nunca publique configuração privada, credenciais, dumps ou modelos no Git.
Não inicie sessão de negociação ou envie ordem para validar instalação.
