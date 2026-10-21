# Revisão do escopo ativo

O fluxo único é: lote → histórico → contexto → hipótese → risco → execução demo
→ resultado confirmado → memória. A sessão controlada no painel é a sessão do
agente autônomo, com recuperação automática e bloqueio de conta real.

## Removido

- Sessão manual de observação, token de operador e estados que exigiam revisão.
- Login/logout por cookie, aprovação manual de versão e telas ocultas desse fluxo.
- Painel local da porta 8768, feed FIX/JEV e otimizador exclusivos desse painel.
- Observador diagnóstico paralelo, revisões humanas e sua auditoria de prontidão,
  que não controlavam nem representavam as decisões do agente atual.
- Dependências pandas/TA-Lib do painel antigo na instalação operacional.

O diagnóstico agora consulta o journal do próprio worker. Decisões novas incluem
o contexto técnico e a janela de candles conhecidos naquele instante. Registros
antigos sem esses campos continuam legíveis e são identificados como incompletos;
nenhum contexto histórico é inventado ou reconstruído como se tivesse sido gravado.

## Mantido

Execução e reconciliação demo, risco, relógio UTC, PostgreSQL, backup, memória,
Timestral, classificação de mercado, gráficos e supervisão. A pesquisa histórica
e o replay permanecem em comandos separados da operação. Ferramentas opcionais
de coleta não são pré-requisitos do robô.

## Preservação

Esta limpeza remove código e controles obsoletos, não registros do banco,
posições, experiências, pesos de modelos ou referências de aprendizado. As
implementações removidas continuam recuperáveis pelo histórico do Git.
Os testes exclusivos dos fluxos retirados foram aposentados; os testes de
execução, risco, recuperação, causalidade e aprendizado continuam no projeto.

Os documentos antigos de planos V1–V4 e entregas intermediárias são histórico de
evolução. Para operar, use o README e os documentos atuais ali relacionados.
