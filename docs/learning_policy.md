# Política de aprendizado e conhecimento

## Fontes locais

`Aprendizado/` contém cinco arquivos: `EBOOK-MANUAL-DO-PULLBACK.pdf`, `Smart Money Concepts - MARRAIK SMC 2 (1).pdf`, `wyckoff-20-portugues-pr.pdf`, `Trading_in_the_Zone.PDF` e `Trading_the_zone_traduzido_portugues.PDF`. As duas últimas aparentam ser versões do mesmo título e precisam de deduplicação bibliográfica. `RESEARCH_NOTES.md` já tem sínteses de Pullback, SMC e Wyckoff; não substitui a conferência de páginas/edição. A extração local de texto PDF não estava disponível durante esta auditoria.

## Ingestão

Usar `data/knowledge/rules.json` como catálogo inicial estruturado. Cada regra guarda ID, título, categoria, síntese curta, documento, localização, condições, observação esperada, invalidação, status, instrumentos/sessões/timeframes, versão e datas de criação/revisão. Armazenar hashes do arquivo e identificadores de edição na próxima etapa. Preferir paráfrases curtas; não copiar passagens extensas.

Status: `extracted`, `needs_review`, `approved_for_research`, `backtested`, `walk_forward_validated`, `approved_for_demo`, `approved_for_live`. Nenhuma transição é automática. Regras sem seção/página confirmada começam `needs_review`. Um livro oferece conceito, não autorização de operação. Conflitos entre fontes devem persistir como registros separados.

## Aprendizado de resultados

O learner atual é regressão logística em features de sinais fechados, com holdout cronológico e piso de amostras. É filtro experimental, não memória semântica nem prova de causalidade. Resultados de backtests sobrepostos não são observações independentes. Próxima versão deve indexar cada experiência por dataset/hash, janela, estratégia/configuração, origem, custos e run; separar treino/validação/teste antes de acumular labels. Propostas ficam inativas até revisão e nova avaliação walk-forward.

## Proibição de promoção autônoma

O agente pode resumir, detectar padrões, produzir hipóteses e relatórios. Não altera regra ou configuração durante sessão ao vivo e não eleva aprovação. `approved_for_live` exige processo humano futuro e continuará sem executor habilitado neste projeto.


## Livermore reference reviewed

The local PDF in `Aprendizado/` was reviewed. The catalog records paraphrased concepts with page references: systematic price observation and forecast/result comparison (Chapter I, pp. 5-6); waiting for trend confirmation (Chapter II, p. 15); and distinguishing individual fluctuations from major moves (Chapter V, pp. 48-49). These are educational prompts for disciplined observation, not Forex evidence or trading signals. The records remain `needs_review` until separately tested in reproducible research.
