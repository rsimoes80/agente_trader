# Revisão das estratégias pela biblioteca

## Estado em 28/10/2026

A estratégia operacional anterior não implementa integralmente as técnicas dos
livros. Ela usa uma hipótese parametrizada de EMA21, ATR14, dois candles M5,
stop nos três candles anteriores com margem de 0,2 ATR e alvo de 2,5R. Esses
números não podem ser apresentados como método extraído e validado da biblioteca.
As novas entradas estão pausadas durante a revisão. A exigência
`AURELIA_REQUIRE_LITERATURE=1` bloqueia propostas sem plano e fontes aprovados.
Não existe plano novo aprovado para execução nesta etapa.

Os 9 PDFs foram extraídos: 3.227 páginas, incluindo OCR quando necessário.
Isso é preparação do material. A leitura semântica é parcial e a interpretação
visual dos gráficos permanece pendente. O arquivo youtube.txt não equivale
à leitura ou transcrição do vídeo. As duas edições de Douglas representam a
mesma obra, não duas confirmações independentes.

## Divergências encontradas

| Caminho | Implementação anterior | Correção necessária |
|---|---|---|
| `agent_strategy.py` | EMA/ATR e gatilho curto | Contexto, qualidade da correção, região, gatilho, invalidação e saída com fontes |
| `literature_strategies.py` | Famílias de pesquisa parametrizadas | Não tratar nomes de famílias como comprovação da técnica do autor |
| `continual_learning.py` | Variantes de alvo 2,5R/3R/3,5R | Reescrita de plano com base bibliográfica agora bloqueada; falta aprendizado por plano |
| Catálogo de conhecimento | Resumos e referências gerais | Revisar contra página original e registrar limites de interpretação |
| Timestral | Previsão numérica de séries | Não equivale a leitor textual nem comprova técnica dos livros |

## Base para a primeira hipótese, ainda não operacional

As páginas abaixo são **páginas físicas do PDF**, não necessariamente a numeração
impressa. São pontos de revisão; não representam consenso entre todos os autores.

- Manual do Pullback, pp. 6–10: profundidade, velocidade relativa, volume e
  preservação da estrutura participam da avaliação conjunta da correção.
- Manual, pp. 11–14: médias aparecem com contexto de swing; regiões também
  incluem retrações e congestões anteriores. EMA21 isolada não reproduz o método.
- Manual, pp. 15–17 e 21–24: região antecede gatilho; invalidação é estrutural;
  o primeiro obstáculo importa para o alvo e a relação entre retorno e risco.
- Pring, pp. 16–26 e 68–72: horizontes de tendência e suporte/resistência dão
  contexto. Romper uma linha não garante reversão nem continuação.
- Wyckoff, pp. 69–75 e 287–292: a resposta do preço confirma ou invalida a leitura;
  linhas isoladas não bastam para entrada.
- Douglas: disciplina, risco e avaliação por série de operações pertencem à
  gestão e ao processo; não constituem gatilho de preço.

A operação somente a favor da tendência é requisito do operador. A escolha
atual de H1 é política do sistema, não fórmula universal atribuída aos livros.
Volume de ticks Forex exige tratamento explícito: não substitui silenciosamente
volume negociado centralizado. Adaptação de swing para M5 exige avaliação própria.

## Fluxo implementado

1. `ingest_learning_library.py`: extração/OCR, hash do PDF e do texto de cada
   página, índice privado e indicação de páginas esparsas.
2. `run_literature_curriculum.py`: leitor textual local produz fichas com
   documento, página, citação, contexto, condições, invalidações e limites.
3. `literature_learning.py`: verifica citação literal; rejeita números sem
   citação, campos inesperados e tentativas de conceder autoridade operacional.
   A verificação literal **não** demonstra que a interpretação está correta.
4. `run_literature_synthesis.py`: tenta combinar fichas em plano de pesquisa
   com contexto, região, gatilho, invalidação e saída. Pode recusar por fontes
   insuficientes. Não gera código nem promove plano para negociação.
5. `literature_basis.py`: exige as cinco etapas, hashes/páginas correspondentes,
   revisão semântica das fichas, aprovação específica de plano e relatório de
   validação antes de aceitar uma base operacional.

Leitor: Qwen/Qwen3-4B-GGUF, revisão
`bc640142c66e1fdd12af0bd68f40445458f3869b`, quantização Q4_K_M.
Runtime local llama.cpp b11962; endpoint restrito a localhost:8791.
Não há treinamento de pesos nem compreensão humana demonstrada por esse fluxo.
O modelo organiza hipóteses; os validadores mantêm a distinção entre texto
extraído, interpretação, pesquisa e autorização operacional.

Texto integral, cache, pesos e configurações privadas ficam fora do Git.
Fichas e progresso são registrados em PostgreSQL; falhas do leitor têm código
próprio e não contam como leitura bem-sucedida. O serviço retoma páginas pendentes.

## Pendências para voltar a operar

- Revisar as interpretações e gráficos relevantes nos originais.
- Compor e revisar um plano completo, com divergências entre autores explícitas.
- Implementar regras observáveis sem informação futura, separando parâmetros
  experimentais das regras literalmente sustentadas pelas fontes.
- Validar estrutura, gatilhos, stops, alvos, custos e horário em replay e período
  separado; comparar com a versão antiga, sem pressupor rentabilidade.
- Criar aprendizado próprio para os planos novos (a aplicação das variantes
  antigas já é recusada para propostas com base bibliográfica) e registrar resultados com versão do plano, fichas e contexto da decisão.
- Registrar aprovação específica após os testes e só então retomar a demo.

## Verificação

`PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_literature_grounding tests.unit.test_entry_trend -v`

Os testes cobrem proveniência literal, números inventados, tentativa de promoção,
fontes adulteradas, etapas ausentes, direção contrária e bloqueio do setup antigo.
Não são evidência de rentabilidade ou de compreensão integral da biblioteca.
