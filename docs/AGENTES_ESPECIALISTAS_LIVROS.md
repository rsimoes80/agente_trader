# Skills e especialistas da biblioteca

O projeto usa oito perfis de especialistas, compartilhando o modelo textual local.
Cada perfil consulta uma skill privada construída com fichas verificadas contra
o PDF e o texto extraído da página. As duas traduções de Douglas pertencem à mesma
obra. Os perfis não simulam uma votação de oito fontes independentes.

A estrutura segue a ideia de consulta sob demanda do projeto
[book-to-skill](https://github.com/virgiliojr94/book-to-skill/tree/7540eefbe74933f5fc84c86becac52486b347778).
A integração é própria: reaproveita nosso OCR, PostgreSQL e referências por página,
sem executar instaladores externos ou copiar o código do conversor. A estrutura
organiza o material disponível; não demonstra compreensão integral dos livros.

## Especialistas

| ID | Escopo |
|---|---|
| pullback | Qualidade da correção, região, gatilho, invalidação e saída |
| pring | Horizontes de tendência, suporte e resistência |
| wyckoff | Estrutura, testes e resposta do preço |
| brooks-trends | Tendências, canais e continuação |
| brooks-ranges | Congestões, rompimentos e falhas |
| smc | Estrutura e conceitos SMC presentes nas fontes |
| douglas | Risco, disciplina e processo; não propõe gatilho de preço |
| livermore | Contexto e princípios, separando relatos históricos de regras |

`knowledge_skills/<id>/SKILL.md` contém instruções versionadas. O pacote privado
correspondente é gerado em `data/references_cache/book-skills/<id>/` e inclui:

- `SKILL.md`: instruções efetivamente carregadas pelo especialista;
- `manifest.json`: fontes, hashes, tópicos, versão e pendências;
- `references/<tipo>.json`: fichas por tipo, carregadas conforme o escopo.

Essas skills são carregadas explicitamente pelo worker do projeto. Não dependem
da descoberta de skills do IDE e não são instaladas globalmente.
Um pacote sem fichas tem status `awaiting_source_cards`; com fichas parciais,
`partial_research_skill`. Nenhum deles recebe rótulo de livro completamente lido.

## Como funciona a análise

O observador de mercado, com acesso somente à leitura na ponte, publica um caso
imutável `book_market_case` no PostgreSQL. Ele contém a tendência H1/H4 calculada
pelo sistema, contexto estrutural e os últimos 12 candles M5 fechados. Esse limite
é um orçamento de contexto experimental, não uma regra atribuída aos autores.
Os dados são insuficientes para algumas técnicas; as condições ausentes precisam
ser relatadas. Volume é identificado como volume de ticks.

Todos os especialistas de uma rodada recebem exatamente o mesmo `case_id` e os
mesmos fatos. Cada um carrega até seis fichas pertinentes, distribuídas entre
os tipos de técnica disponíveis. Contagens de fichas disponíveis e carregadas
acompanham o relatório; não se presume consulta ao livro inteiro.

A resposta estruturada precisa vincular cada conclusão a IDs de fichas e IDs de
fatos observados, incluindo invalidação e condições ausentes. Campos de ordens,
fontes desconhecidas são rejeitados. Se o modelo declara suporte mas lista condições
ausentes, o adaptador rebaixa explicitamente a conclusão para `uncertain`, registrando
a classificação original, a correção e o hash da resposta. O validador continua
recusando conclusões positivas com condições ausentes. Nenhuma correção pode
promover uma conclusão ou dispensar erro de fonte ou escopo.
Uma citação correta não prova que a interpretação é correta: as conclusões
continuam marcadas como pendentes de revisão semântica.

O coordenador preserva conclusões favoráveis, contrárias, lacunas e divergências.
Confere cobertura de contexto, região, gatilho, invalidação e saída. Mesmo com
todas as etapas presentes, produz somente `candidate_for_semantic_review`, nunca
uma ordem. Tendência H1 não confirmada impede a chamada dos especialistas ao modelo.

A análise é assíncrona, com timestamp e latência explícitos. Um parecer antigo
não representa autorização para uma entrada no mercado atual. O acesso ao modelo é serializado por um lock local entre leitor, síntese e
especialistas; a espera na fila não consome o timeout HTTP. O modelo local
Qwen3-4B é compartilhado com o leitor e sua adequação às análises precisa ser medida.

## Operação

Registrar a curadoria textual parcial do Manual (sem aprovação operacional),
seguida da geração dos oito pacotes:

```bash
.venv/bin/python curate_book_skill.py
```

Gerar/atualizar os oito pacotes, sem inferência:

```bash
.venv/bin/python run_book_specialists.py --build-only
```

Analisar uma vez o caso mais recente publicado pelo observador:

```bash
.venv/bin/python run_book_specialists.py --specialists pullback pring wyckoff
```

Reproduzir um caso histórico congelado (a opção `--case` espera o esquema gerado
por `market_case`, não candles avulsos):

```bash
.venv/bin/python run_book_specialists.py --case data/reports/meu-caso.json --specialists pullback
```

Instalar o serviço de pesquisa:

```bash
.venv/bin/python install_book_specialists.py --specialists pullback pring --interval 900
systemctl --user status agente-trader-book-specialists.service
journalctl --user -u agente-trader-book-specialists.service -n 20 --no-pager
```

O padrão limita a rodada a Pullback e Pring para controlar carga na VM. Os demais
perfis estão disponíveis por `--specialists`, de acordo com o assunto avaliado.
Rodadas repetidas com o mesmo caso, versões de skill e especificação do modelo
são deduplicadas. A especificação registra revisão do modelo, versão do prompt
e limites de contexto/saída. Pacotes são
reconstruídos a cada ciclo para incorporar novas fichas do leitor. Falhas do modelo
ou de validação produzem relatório de falha; não passam a ser confirmação do setup.

Pareceres individuais ficam em `book_specialist_analysis`, a composição em
`book_council_analysis`, ambos no PostgreSQL. O último relatório completo é salvo
em `data/reports/book-specialists/latest.json`. Conteúdo derivado dos livros e
relatórios ficam privados; apenas o código e as instruções gerais vão ao Git.

## Limites desta entrega

Esta integração melhora a análise e a consulta às fontes. Ainda faltam leitura
semântica completa, revisão visual dos exemplos, avaliação da qualidade dos
pareceres em casos históricos e transformação de um plano revisado em estratégia
executável. Os testes de contrato não medem rentabilidade ou fidelidade semântica.
As entradas do agente de negociação permanecem pausadas e o bloqueio de base
bibliográfica continua ativo. Nenhum especialista possui cliente de execução MT5.

## Evidência da primeira execução

A rodada automática no mercado corrente registrou ausência de tendência H1
confirmada. O primeiro teste histórico excedeu o timeout inicial; após ajuste
da fila e do orçamento, o modelo respondeu, mas foi rejeitado por declarar suporte
com condições ausentes (`MISSING_CONDITION_CANNOT_SUPPORT`). Esse caso motivou o
rebaixamento explícito para incerteza, coberto por teste de regressão.
O desempenho observado não autoriza uso como gatilho imediato de M5. Ainda não
foi demonstrada qualidade semântica consistente em uma amostra de casos reais.
