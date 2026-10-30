# Elephant–Goldfish no agente trader

## Instalação e limites de escopo

O plugin EGM foi instalado pelo CLI oficial do Codex para o usuário Rafael,
fora do Git deste projeto. O marketplace está fixado no commit
`403d8881d62022490637d740657b33f01e321ea8` do repositório
https://github.com/google/elephant-goldfish-model. O plugin é `egm@egm`, versão
0.1.0. O instalador mantém o pacote completo no cache do Codex; não copiamos
personas, padrões, assets ou o Git externo para o agente_trader.

Reproduzir:

```bash
/home/rafael/.local/bin/codex plugin marketplace add google/elephant-goldfish-model --ref 403d8881d62022490637d740657b33f01e321ea8 --json
/home/rafael/.local/bin/codex plugin add egm@egm --json
/home/rafael/.local/bin/codex plugin list --json
```

Instale no mesmo usuário/conta Codex usado pelos terminais Maestri. Se houver
outra configuração CODEX_HOME, confira a instalação naquela sessão. Abra uma
sessão nova para descobrir as skills instaladas. Localize o bundle pelo caminho
retornado pela instalação/listagem; não assuma que o cache e a versão serão
sempre os mesmos. Não executar atualização automática do marketplace durante
um experimento; uma atualização requer registrar a revisão nova e repetir a
verificação da integração.

EGM usa as sessões do agente hospedeiro; não é um novo modelo local nem ocupa
VRAM por carregar pesos próprios. Instalação e descoberta não demonstram que os
fluxos completos do plugin foram testados no seu Maestri.

## O que foi integrado

1. O Orquestrador assume o papel Elephant: mantém objetivos, restrições e decisões.
2. `prepare_egm_review.py` consulta somente um caso existente em transação de banco
   read-only e gera um pacote privado com hipótese, fontes e código congelados.
3. Dois revisores recebem contextos novos, sem histórico do autor ou do outro
   revisor. Cada um lê a persona original do plugin e um critério local específico.
4. O Orquestrador guarda os pareceres individuais e consolida achados, sem votar
   aprovação de ordens, editar fichas ou mudar estado operacional.

Este é um piloto adaptado de duas revisões, não a execução integral das cinco
etapas de `egm-review`. Os critérios locais em `docs/egm/standards/` adaptam a
inspeção para fontes dos livros, causalidade e correspondência com o código.
Os padrões e personas originais permanecem no plugin.

O fluxo completo EGM tem gates de interação; a revisão disponibiliza o preset
`Step=uninterrupted` para consolidar etapas. Não é correto prometer que todas as
skills upstream deixam de pedir decisões. Neste piloto a configuração de duas
revisões e uma rodada já está definida; não há confirmação por achado. Decisões
arquiteturais novas e autorização operacional não decorrem da instalação.

## Pacote de evidências

Preparar o caso mais recente disponível, congelando sua identidade:

```bash
.venv/bin/python prepare_egm_review.py
```

Para um caso explicitamente selecionado:

```bash
.venv/bin/python prepare_egm_review.py --case-id ID_DO_CASO
```

O comando imprime a pasta criada em `data/reports/egm/`. Ela contém:

- `hypothesis.md`: rascunho de uma hipótese compradora de pullback;
- `case.json`: o caso original, incluindo case_id e as_of;
- `sources.json`: nove páginas textuais do Manual, com PDF/hash e hash do texto;
- `code_*.txt`: snapshots de três arquivos para a comparação com a implementação;
- `manifest.json`: hashes dos arquivos de entrada, revisão upstream e orçamento.

A extração textual não contém imagens: a revisão visual continua pendente.
A cópia curta de M5 não reconstrói todo o histórico H1/H4. O comando não coleta
novas cotações, não envia ordens e não muda aprovação ou estado de negociação.
O rascunho gerado é o mesmo piloto; não é um gerador automático de estratégias
nem cria uma hipótese operacional válida para qualquer novo caso.

Verificar que as entradas não mudaram:

```bash
.venv/bin/python prepare_egm_review.py --verify CAMINHO_DA_PASTA
```

Não altere entradas enquanto os revisores estiverem trabalhando. Se houver
correção, faça uma nova revisão/versionamento explícito e mantenha o pacote
original. Relatórios novos não alteram os hashes das entradas do manifesto.

## Como usar pelo Maestri

Reutilize o Orquestrador. O Observador pode localizar o caso e a Biblioteca pode
preparar uma hipótese quando isso for autorizado. Para Goldfish, o Orquestrador
precisa de uma ferramenta nativa capaz de criar contexto novo, por exemplo
`spawn_agent` com `fork_turns="none"` ou `fork_context=false`, conforme a API real.
Passar somente a lista de leitura, a persona, o critério e o alvo; não passar
histórico, conclusões esperadas ou pareceres de outros revisores.

Um terminal Revisor que participou da discussão não é, por isso, Goldfish.
A revisão entre os terminais existentes continua útil, mas a revisão EGM isolada
exige um contexto novo verificável. Trocar o nome do papel ou escrever “esqueça a
conversa” não estabelece esse isolamento. Se a ferramenta não existir, registre
a limitação e não simule uma revisão independente na mesma conversa.

Contexto novo não cria isolamento de filesystem, memória externa ou permissões.
A restrição de somente leitura do piloto é contratual nas instruções dos revisores;
a API de delegação usada não restringe a lista de ferramentas por agente. Não
reivindicar uma sandbox separada. Proíba leitura de conversas/memória e relatórios
alheios e não forneça acesso operacional na tarefa.

Prompt de disparo para o Orquestrador, após preparar um pacote:

```text
Use o piloto de docs/EGM_ORQUESTRACAO.md para revisar a pasta indicada abaixo.
Pacote: CAMINHO_IMPRESSO_PELO_PREPARADOR
A configuração de duas revisões somente leitura e uma rodada está autorizada.
Verifique o manifesto. Descubra o caminho real do plugin EGM instalado.
Crie dois revisores nativos com contexto novo: um lê agents/design_critic.md
com docs/egm/standards/source-fidelity.md; outro lê agents/codebase_details.md
com docs/egm/standards/implementation-fidelity.md.
O primeiro recebe hipótese, manifesto, caso e sources.json. O segundo recebe
hipótese, manifesto, caso e os três snapshots code_*.txt. Não compartilhe conversa
anterior nem o parecer de um com o outro. Aguarde a conclusão real dos dois e
registre arquivos lidos, limitações, falhas, evidências e recomendações.
Salve os pareceres e a consolidação na pasta privada do pacote. Não altere
estratégia, fichas, pesos, serviços, políticas de risco ou estado de negociação.
Não envie ordens. Não inicie rodadas recorrentes ou correções automáticas.
Se não houver suporte a contexto novo, relate a limitação.
```

## Critério de conclusão

O piloto está concluído quando dois revisores realmente retornam, suas identidades
de caso coincidem, os hashes das entradas continuam válidos e os achados são
consolidados com pendências explícitas. Uma revisão completa pode concluir que
uma hipótese está incompleta. Isso não constitui validação de rentabilidade,
aprovação de plano para demo, treinamento do agente ou implantação operacional.

O teste nativo realizado aqui comprova o piloto de delegação com personas
instaladas e padrões locais. Não comprova que todos os comandos do plugin foram
executados por todos os terminais ou contas do Maestri. Não foi feita auditoria
forense de isolamento nem disponibilizada trilha completa de ferramentas dos
subagentes; os relatórios identificam as leituras declaradas e fatos conferíveis.
