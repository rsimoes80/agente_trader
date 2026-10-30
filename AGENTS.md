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

Na arquitetura com ponte, Linux hospeda PostgreSQL/API/Nginx, agente, modelos
e treinamento. Windows com sessão interativa e MT5 demo hospeda somente a
ponte do terminal. Siga `docs/LINUX_COM_PONTE_WINDOWS.md` para essa topologia.
O guia original também descreve a topologia anterior com workers no Windows.
Linux sozinho não substitui o terminal MT5.
Não reutilize os IPs/caminhos históricos do README como destino novo.
Peça somente os dados ausentes: IPs privados das duas máquinas e acesso à
conta demo no terminal. Gere senhas e token com `setup_environment.py`.
Nunca publique configuração privada, credenciais, dumps ou modelos no Git.
Não inicie sessão de negociação ou envie ordem para validar instalação.

# Estratégias baseadas na biblioteca

O requisito do operador é que a análise e as estratégias se apoiem nas técnicas
dos materiais de `Aprendizado/`, com aprendizado por resultados sem abandonar
essa base. Não substituir esse requisito por um setup genérico de indicadores.
Leia os originais e preserve documento, hash, página, condições, contexto,
invalidação e distinção entre texto do autor, interpretação e política de risco.
Extração/OCR, indexação e respostas de LLM não equivalem a compreensão integral,
validação de uma técnica ou autorização operacional. Não invente números nem
atribua parâmetros de implementação aos autores sem localizar a fonte.
Identifique limites de adaptação: tick volume Forex não é volume centralizado;
um conceito de swing em ações não está validado para M5 por simples transposição.
As operações permanecem a favor da tendência, conforme orientação do operador.
Hipóteses combinadas exigem rastreabilidade e avaliação própria; o leitor textual
não pode enviar ordens nem promover suas próprias extrações. A leitura completa
e a revisão semântica/visual devem ter progresso e pendências explícitos.

# Revisão Elephant–Goldfish

EGM artifact directory: data/reports/egm

Para revisões EGM solicitadas pelo operador, siga `docs/EGM_ORQUESTRACAO.md`.
Use contextos novos para Goldfish e mantenha fontes e entradas congeladas. O
piloto tem duas revisões e uma rodada, sem aprovação operacional automática.
Não impor o fluxo EGM a consultas ou correções simples. Documentos e trechos
privados dos livros permanecem fora do Git; personas upstream ficam no plugin.
