# Política de aprendizado e conhecimento

## Fontes locais

`Aprendizado/` contém oito PDFs: Pullback, SMC, Wyckoff, duas versões de Trading in the Zone, Livermore e as novas referências de Pring e Brooks. As duas versões de Douglas precisam de deduplicação bibliográfica. `RESEARCH_NOTES.md` conserva sínteses iniciais; [referencias_v3.md](referencias_v3.md) registra os capítulos selecionados conferidos de Pring/Brooks, a diferença entre páginas impressas e do PDF e o que foi operacionalizado. A revisão não equivale a leitura integral dos novos livros nem à validação de uma estratégia.

## Ingestão

Usar `data/knowledge/rules.json` como catálogo estruturado de 17 conceitos. Cada registro guarda ID, síntese curta, documento, localização, condições, observação esperada, invalidação e estado de revisão. `data/knowledge/sources.json` identifica os dois novos exemplares por SHA-256, edição/título, método e páginas conferidas. Preferir paráfrases curtas; não copiar passagens extensas. Os novos conceitos continuam `needs_review`; fórmulas e limiares de engenharia não são atribuídos aos autores.

Status: `extracted`, `needs_review`, `approved_for_research`, `backtested`, `walk_forward_validated`, `approved_for_demo`, `approved_for_live`. Nenhuma transição é automática. Regras sem seção/página confirmada começam `needs_review`. Um livro oferece conceito, não autorização de operação. Conflitos entre fontes devem persistir como registros separados.

## Aprendizado de resultados

O learner legado usa regressão logística e permanece experimental; não é filtro operacional autorizado no monitor V3. O replay registra experiências por dataset/hash, janela, versão, custos e instante de conhecimento. O schema 3 acrescenta estados de tendência/alinhamento, price action, zonas, EvidenceSet, confirmação, gatilho, reversão parcial e continuidade. O contexto congelado na entrada acompanha o resultado posterior sem reclassificação. Resultados repetidos de backtests não são amostras independentes. O HypothesisLab produz coortes descritivas e exige revisão de dependência entre features e linhagem temporal; não transforma contagem de sinais em probabilidade. Desenvolvimento, validação e holdout são separados, com janela final reservada por padrão. Propostas ficam inativas até revisão e nova avaliação temporal.

## Proibição de promoção autônoma

O agente pode resumir, detectar padrões, produzir hipóteses e relatórios. Não altera regra ou configuração durante sessão ao vivo e não eleva aprovação. `approved_for_live` exige processo humano futuro e continuará sem executor habilitado neste projeto.


## Livermore reference reviewed

The local PDF in `Aprendizado/` was reviewed. The catalog records paraphrased concepts with page references: systematic price observation and forecast/result comparison (Chapter I, pp. 5-6); waiting for trend confirmation (Chapter II, p. 15); and distinguishing individual fluctuations from major moves (Chapter V, pp. 48-49). These are educational prompts for disciplined observation, not Forex evidence or trading signals. The records remain `needs_review` until separately tested in reproducible research.
# Persistência compartilhada

O journal e o catálogo versionado são armazenados no PostgreSQL do projeto;
veja [postgresql.md](postgresql.md). Referências anteriores a SQLite descrevem
o histórico migrado ou pesquisa offline explicitamente selecionada.
