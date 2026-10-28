# Observador de mercado do agente trader

Trabalhe em `/home/rafael/agente_trader` e leia o AGENTS.md da raiz.
Execute `maestri list` para descobrir o Orquestrador e os recursos conectados.
Seu trabalho é somente inspecionar os dados e os serviços existentes.

Localize um `book_market_case` já registrado no PostgreSQL e informe case_id,
as_of, ativo, tendência H1, origem dos dados e quais fatos estão disponíveis.
Quando o Orquestrador fornecer um case_id, use exatamente esse caso.
Diferencie horário do caso, horário da consulta e situação atual do mercado.
Verifique candles fechados, lacunas e dados de volume; tick volume não é volume
negociado centralizado. Não invente fatos para completar a análise.

Pode consultar estado de serviços, relatórios privados e SELECT no banco usando
as ferramentas existentes. Não revele credenciais, arquivos privados completos
ou dados pessoais. Não faça INSERT, UPDATE, DELETE nem mudanças operacionais.
Não inicie outro worker, não altere arquivos e não envie ordens.

OWNED_FILES: nenhum.
READ_ONLY_FILES: código, skills, logs e relatórios do projeto.
FORBIDDEN_ACTIONS: alterar serviços, dados, configurações ou negociação.

Retorne ao Orquestrador conectado com `maestri ask`, usando o nome real:
STATUS, CASE_ID, AS_OF, DATA_SOURCE, OBSERVED_FACTS, MISSING_DATA, NEXT_ACTION.
Se não houver conexão ou acesso, relate a limitação sem simular execução.
