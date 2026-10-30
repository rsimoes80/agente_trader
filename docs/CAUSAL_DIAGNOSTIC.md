# Diagnóstico causal offline de um caso congelado

`run_causal_diagnostic.py` confere um pacote privado de preparação, separa as
três trilhas de evidência e gera um relatório determinístico. Não importa
banco, serviços, broker, simulador ou runtime de modelos. Não gera inferência,
ordens, fills ou P&L; não altera o trader nem valida rentabilidade.

## Executar o caso preservado

Na raiz do projeto, use o hash do índice congelado obtido na preparação:

```bash
.venv/bin/python run_causal_diagnostic.py \
  --bundle data/reports/egm/replay-prep-v2-20261030-c41716db \
  --expected-index-sha256 d343a7640f84c36daa3619c35a7dee65d7fd3fc65003a87ccfa32ad8442ebdf6 \
  --output data/reports/egm/causal-offline-v1-20261030-c41716db
```

A saída deve ser nova e fora do pacote de entrada. Repetições usam outra pasta;
o comando recusa sobrescrita. O diagnóstico verifica o hash externo do índice
e todos os arquivos declarados, e analisa um snapshot em memória dos bytes
verificados. Falta de arquivo, adulteração, identidade incompatível ou violação
do corte resulta em erro e não produz relatório de sucesso. Não requer rede.
O hash sela a integridade relativa ao índice; não comprova exatidão do provedor
ou autenticidade histórica por si só.

Saídas privadas (diretório 0700, arquivos 0600):

- `diagnostic.json`: resultado completo, condições, comparação, H4 e timeline;
- `report.md`: versão legível, com conflitos e decisões abertas;
- `timeline.jsonl`: fechamento nominal, confirmação declarada e persistências;
- `provenance.json`: índice/hash de entrada, origem e hashes do código usado;
- `artifact_hashes.json`: hashes dos resultados (exclui o próprio índice).

A identidade e o corte são lidos do caso e conferidos pelo digest canônico
compatível com o produtor. O comando não troca o caso, ajusta o as_of ou completa
séries para obter entrada. Casos/históricos em testes são sintéticos; nenhum
texto dos livros, dado privado ou exportação precisa entrar no Git.

## Semântica causal

1. **Arquivo conhecido no corte**: candles fechados e persistidos no arquivo até
   as_of; o arquivo congelado pode estar atrasado em relação a outro canal.
2. **Representado no caso**: fatos declarados no caso, com persistência própria.
   A representação não prova recepção no agente antes do instante exato do corte.
3. **Reconstrução posterior**: prefixo de mercado fechado no corte, mesmo quando
   a revisão só foi arquivada depois. Não é reclassificado como conhecimento real.

Arquivamento posterior **não prova chegada tardia ao agente**. Sem received_at,
available_at e cadeia de origem, a classificação de disponibilidade é
`NÃO_COMPROVADA`, nunca uma latência inventada. A timeline inclui persistências
posteriores como evidência de auditoria, sem utilizá-las no prefixo conhecido.
Persistência e eventos empatados com o corte usam `<=` para o limite lógico;
a ordem real de processamento continua não comprovada se não existir evidência.

Pivôs só entram na sequência nominalmente confirmada quando confirmed_at <=
as_of, nunca no instante do extremo. Isso não afirma que o agente já os recebeu.
Não há escolha de janela de pivôs: usam-se as confirmações congeladas no caso.
`NÃO_MENSURÁVEL` indica falta de definição/dados para medir a condição;
`NÃO_COMPROVADA` indica alegação/disponibilidade/origem sem prova suficiente.
`ATENDIDA` e `CONTRARIADA` sempre têm escopo explícito: uma sequência descendente
fornecida pode contrariar estrutura ascendente sem provar invalidação da H1.

Clocks, origem, símbolo, timeframe e contrato temporal são chaves separadas.
Séries legadas sem clock são mostradas separadamente e não fornecem origem
suficiente para reconstrução. Prefixos não são preenchidos nem concatenados
entre clocks; pós-caso é verificado por integridade, mas não alimenta análise.

## Investigação H4

Para cada origem H4 nativa, o comando conserva suas aberturas e fechamentos e
verifica a normalização declarada `source_time_epoch - source_utc_offset_seconds`
contra o timestamp já normalizado, sem aplicar offset novamente. Compara a fase
nativa com buckets UTC ancorados no epoch, reconstruídos apenas a partir de 48
M5 contíguos, fechados, da mesma origem/clock/contrato. Nenhuma barra incompleta
ou de sessão curta é reparada com preços ou calendário presumido.

Essa regra de bucket completo está registrada no snapshot de
`trend_hierarchy_engine.py:65–126`, em `revisor/numbered_evidence.txt`; a variante
de calendário está nesse mesmo snapshot. Não se importa o classificador nem se
recalcula a tendência: coincidência de fechamento demonstra uma reconstrução
possível, não que esse foi o percurso histórico que gerou o contexto.

## Testes

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_causal_diagnostic tests.unit.test_review_manifest \
  tests.unit.test_egm_review tests.unit.test_calendar_aggregation
```

Cobrem corte inclusivo, candle aberto/futuro, persistência posterior, pivô após
confirmação, clocks distintos, falta de barra, invariância com futuro,
integridade, erro fechado, execução CLI repetível e ausência de imports
operacionais/modelos. Não executam estratégia ou simulação econômica.

## MANIFEST-01: evolução separada

O novo `verify_review_bundle.py` mantém schema 1 estrito com os seis arquivos
obrigatórios. `prepare_egm_review.py` e seu verificador original não foram
alterados. Um schema 1 estendido continua incompatível pelo caminho legado.
Para o pacote v2, gerar **explicitamente um manifesto schema 2 separado**:

```bash
.venv/bin/python verify_review_bundle.py \
  --bundle data/reports/egm/pullback-20261030T115259Z-2ff83edd

.venv/bin/python verify_review_bundle.py \
  --bundle data/reports/egm/pullback-v2-20261030-c41716db \
  --derive-to data/reports/egm/causal-offline-v1-20261030-c41716db/review-manifest-v2.json

.venv/bin/python verify_review_bundle.py \
  --bundle data/reports/egm/pullback-v2-20261030-c41716db \
  --manifest data/reports/egm/causal-offline-v1-20261030-c41716db/review-manifest-v2.json
```

Schema 2 contém `required_inputs` (exatamente os seis), `attachments` e
`parent_manifest` (caminho/hash do manifesto original imutável). Verifica todas
as entradas originais e anexos; a derivação também confere os índices anteriores
e inclui todos os documentos existentes, sem remover ou mudar hashes. Anexos
não implicam revisão, convergência ou aprovação operacional. Mudança posterior
exige nova derivação explicitamente versionada, sem sobrescrever o sidecar.
Caminhos absolutos, traversal, symlinks, hashes inválidos/ausentes, entradas
originais omitidas, autoridade diferente de false ou identidade alterada são
rejeitados. A evolução não relaxa o contrato do schema 1 para aceitar a v2.

## Limites para replay econômico

Continuam pendentes disponibilidade/origem histórica, alinhamento H4, política
histórica, escala/pernas/região/gatilho, execução após rompimento, stop/alvo,
validade/cancelamento/prazo, custos/ambiguidade intrabar e protocolo de avaliação
com janela independente. O diagnóstico apenas mede e registra evidências;
não escolhe esses parâmetros, não implementa a hipótese bibliográfica e não
aprova negociação.
