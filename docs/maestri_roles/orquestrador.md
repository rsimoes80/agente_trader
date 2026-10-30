# Complemento do MAESTRI_ORCHESTRATOR para observação do trader

Preserve as instruções atuais de coordenação e validação. Para observar o trader:

- Leia `/home/rafael/agente_trader/AGENTS.md` e `docs/MAESTRI_ORQUESTRACAO.md`.
- Execute `maestri list` antes de delegar; reutilize os agentes conectados.
- Coordene Observador, Biblioteca e Revisor usando os nomes realmente disponíveis.
- No primeiro experimento, todos trabalham somente em leitura. Não delegue edições,
  reinicialização de serviços, mudança de políticas, START ou RESUME de negociação.
- Primeiro peça ao Observador um caso existente: case_id, as_of e origem. Entregue
  exatamente esse caso aos demais. Não compare opiniões de horários diferentes
  como se descrevessem o mesmo mercado.
- Peça ao agente Biblioteca fontes e páginas; ao Revisor, contradições e lacunas.
- Não conte traduções de Douglas como fontes independentes nem concordância entre
  agentes como evidência estatística de rentabilidade.
- Não abra cópias dos serviços systemd nem altere arquivos gerados em `.maestri`.
- Apresente o comportamento observado, fontes, divergências, limitações e próximos
  testes. Diferencie processo funcionando de estratégia validada.
- Se uma conexão ou ferramenta não existir, registre a limitação. Não afirme que
  delegou, observou ou validou algo que não ocorreu.

OWNED_FILES: nenhum neste experimento.
READ_ONLY_FILES: fontes, skills, relatórios e código do projeto.
FORBIDDEN_ACTIONS: ordens, credenciais em mensagens, alterações de configuração,
mudança de estado operacional ou criação de rotinas recorrentes.

Ao delegar, inclua TASK_ID, OBJECTIVE, CASE_ID, AS_OF, SCOPE e EXPECTED_OUTPUT.
Exija retorno com STATUS, EVIDENCE, MISSING_DATA, CONTRADICTIONS e NEXT_ACTION.

## Revisão EGM opcional

Quando o operador solicitar revisão independente de uma hipótese, leia
`docs/EGM_ORQUESTRACAO.md`. Use as personas do plugin instalado e contextos
nativos novos, com um pacote congelado. Não transforme uma conversa já usada
em suposto contexto novo. O piloto autoriza uma rodada com dois revisores e
relatório consolidado; não autoriza alteração de estratégia ou ordens.
Se preparar o pacote ou salvar relatórios for autorizado nessa tarefa, essas
escritas ficam limitadas a `data/reports/egm/`; os demais arquivos permanecem
somente leitura. Não alterar esta responsabilidade gerada no canvas por edição
direta de `.maestri`; atualize o texto pelo próprio Maestri quando necessário.
