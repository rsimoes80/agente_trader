# Replay experimental isolado de preço

O pacote `aurelia_fx.research_price` e `run_price_replay.py` executam um cenário
retrospectivo sem importar estratégia operacional, risco de produção, banco,
modelos ou broker. Nenhum caminho de execução envia ordens. O caso preservado
continua auditoria, sem selecionar um exemplo favorável como substituto.

## Fonte, requisito e adaptação

A base conceitual é o Manual do Pullback: profundidade/velocidade/estrutura
(pp.6–10), região das médias simples (p.11), vela em alta e rompimento posterior
(pp.15–16), stop na correção e primeiro alvo no topo anterior com espaço bruto
mínimo de2R (p.17). A proveniência completa e a inspeção visual parcial estão
em pacotes privados; não se incorporam textos, imagens ou fichas ao Git.

Somente long com contexto H1 comprador atende ao requisito do operador desta
hipótese. A definição mecânica H1, o detector M5, os prazos e o modelo econômico
são adaptações experimentais. O ramo de preço **não mede volume centralizado**
e não declara que tick volume satisfaz o critério original. Também não chama a
adaptação de aplicação literal da regra de três critérios do autor.

A H1 mecânica usa somente os dois últimos highs/lows confirmados e pode manter
a classificação após quebra de fundo até a confirmação de novos pivôs. Essa
limitação foi aceita antes dos resultados; não equivale a BULL_CONFIRMED da
produção ou a garantia de fundo H1 intacto.

O protocolo privado fixa todas as escolhas antes dos resultados: swings
estritos com confirmação tardia, H1 por buckets UTC completos de12M5 da mesma
origem/clock, impulso A/B, fundo protegido A e correção C. A correção deve
preservar A, devolver menos de dois terços e ser mais lenta, com corpos menores.
Região única: faixa entre SMA9/17/21 do fechamento anterior. A candidata é
close>open com contato nessa faixa; ativação e rompimento só em barra posterior.

Stop e alvo ficam congelados; lote/unidades não são dimensionamento operacional.
Custos, sessão, validade, prazo máximo e janelas são definidos no protocolo,
sem valores herdados silenciosamente da configuração do trader. Este primeiro
cenário usa preços bid e spread constante por barra como hipóteses não
verificadas; comissão/slippage são hipóteses de pesquisa, não tarifas históricas
comprovadas. Não há conta/equity ou promoção automática.

## Execução e causalidade

- Um único pending/posição, uma operação por impulso preenchido ou ambíguo.
- H1 usada antes de tentar entrada conhece somente barras fechadas até a abertura.
- Trigger estritamente acima da high da candidata; compra ask por trigger/open,
  spread e slippage adverso. Gap não move stop/alvo; geometria e2R são reavaliados.
- Expiração é exclusiva; validade de entrada é distinta do prazo da posição.
- Stop/estrutura rompidos sem gatilho cancelam pending quando a barra fecha.
  Se rompimento e stop estão na mesma barra sem ordem observável, há censura.
- Gaps conhecidos na abertura precedem testes high/low; target limit não recebe
  melhoria por gap. Stop e alvo antes de tempo/sessão/fim da partição.
- Ambiguidade stop/alvo ou entrada/stop conserva P&L principal ausente.
  Na entrada incerta, limites de horizonte ficam nulos: cenários locais de
  stop/target não abrangem gaps posteriores e não são limites de perda. Entrada incerta impõe quarentena pelo horizonte máximo.
- Qualquer lacuna M5 reseta contexto/aquecimento, cancela pending e censura
  exposição sem inventar preenchimento. Não mistura clocks ou revisões.
- Cada partição inicia contexto/aquecimento/estado/exposição próprios e liquida
  posição observável no fim. Ambas as janelas são retrospectivas; não há holdout
  inédito nem treino ou ajuste de parâmetros entre janelas.

## Selar antes de executar

O experimento privado contém `protocol.json`, `rationale.md`, `freeze.json`
e `implementation_notes.md` com as resoluções da revisão anterior aos resultados.
O freeze registra os hashes e o horário anterior aos resultados. O comando
verifica o índice externo do pacote de preparação e todos os arquivos
congelados; seleciona apenas os exports M5 indicados, da mesma identidade.
A reconstrução usa relógio lógico de fechamento, sem alegar disponibilidade
real histórica do arquivo ou retroatribuir política/env atual ao passado.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python run_price_replay.py \
  --experiment data/reports/egm/NOVO_EXPERIMENTO \
  --protocol-sha256 HASH_DO_PROTOCOLO --seal

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python run_price_replay.py \
  --experiment data/reports/egm/NOVO_EXPERIMENTO \
  --protocol-sha256 HASH_DO_PROTOCOLO \
  --execute --execution-seal-sha256 HASH_RETORNADO_PELO_SELO \
  --output data/reports/egm/NOVO_EXPERIMENTO/resultados-01
```

O selo adicional inclui todos os imports locais (inclusive os initializers),
hashes das duas suítes e das notas, versão Python, protocolo e identidade/hash dos
dados; alteração exige novo experimento/selo, não execução silenciosa com o
resultado anterior. O comando recusa sobrescrita. Arquivos de resultados e
protocolos privados ficam fora do Git, com diretórios0700 e arquivos0600.

Saídas: `summary.json`, `result.json`, eventos/decisões/operações JSONL,
`report.md`, proveniência e hashes. P&L conhecido parcial é identificado como
parcial quando há censura; total e média completa ficam ausentes. Resultados
negativos, zero entradas e ambiguidades permanecem no registro. Limites de
cenário não são lucros realizados. O retorno emR usa perda planejada ao stop,
custos e unidades fixas; não simula orçamento ou política de risco de produção.

## Validação

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_research_price tests.unit.test_research_price_data \
  tests.unit.test_causal_diagnostic tests.unit.test_review_manifest \
  tests.unit.test_egm_review tests.unit.test_calendar_aggregation
```

Fixtures são sintéticas. Testes cobrem confirmação/prefixos, H1 sem candle
aberto, clocks/gaps, entrada posterior, expiração, custos reconciliados,
slippage/stop de gap, target limit, holding, sessão, partições, censura,
quarentena, não reutilização de impulso, integridade e reprodução. Nenhum teste
contém páginas privadas ou precisa conectar-se ao terminal/banco.

Não há garantia de vantagem, adequação de amostra, fidelidade integral aos livros
ou prontidão operacional. Uma única execução com parâmetros fixos é evidência
descritiva do cenário. Resultados favoráveis não autorizam fichas, pesos,
serviços, políticas ou negociação.
