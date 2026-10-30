# Critério do piloto: hipótese, dados e implementação

Leia a hipótese, o caso e os snapshots de código congelados no pacote. Não use
conversa anterior nem resultados de outros revisores. Diferencie regras propostas
de funcionalidades que o documento afirma existirem. Uma proposta não implementada
é uma pendência, não uma funcionalidade existente quebrada.

Verifique causalidade: candle fechado, pivô confirmado, horário, tendência conhecida
no instante e contexto suficiente. Não preencha histórico, custos ou séries ausentes.
Aponte onde código e hipótese divergem e quais decisões faltam para implementá-la.
Mantenha a distinção entre candidato de pesquisa, base bibliográfica aprovada,
controle de risco e autorização de execução. Não conclua comportamento de todos
os módulos a partir dos três snapshots fornecidos.

Avalie o plano de teste: replay cronológico, custos, definição de entrada e saída,
janela separada e ausência de dados futuros. Se não houver especificação completa,
registre-a como pendente; não escolha parâmetros novos em nome do autor.

Retorne: arquivos realmente lidos, case_id/as_of, severidade, localização/linhas,
evidência no código, correção proposta e validação restante. Não editar código,
dados, serviços ou configuração. Não enviar ordens e não executar o sistema.
