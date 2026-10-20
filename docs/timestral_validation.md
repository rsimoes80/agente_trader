# Validação Timestral — 20/10/2026

## Instalação e inferência

- SDK oficial `a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff`, pacote 1.0.0.
- Modelo `mistralai/Timestral-209M`, revisão
  `9874d252ab0aae16f7f7c999f98f98d6ad7d8365`.
- Windows 11, Python 3.14, PyTorch 2.14.1 CPU, ambiente isolado.
- Pesos instalados em cache ignorado pelo Git. Inferências consecutivas com
  a mesma entrada produziram quantis idênticos. Latência inicial medida de
  aproximadamente 1.044 ms; outra previsão ao vivo medida em 795 ms.
  Esses valores não incluem a inicialização fria/carregamento dos pesos.
- O modelo não foi instalado na VM de 1,6 GB; a API Linux consulta PostgreSQL.
- WSL2 e CUDA possuem configuração documentada, sem validação neste equipamento.

## Persistência

Backup PostgreSQL antes da migration. As quatro tabelas da extensão foram
adicionadas sem alterar o journal operacional. Testes de DDL e gravação usam
schema exclusivo, dentro de transação revertida ao final. Foram verificados
rollback vazio, bloqueio de rollback com histórico, checksum, unicidade,
transação integral, imutabilidade, avaliação posterior e corte temporal V4.
O teste opcional com modelo verdadeiro e PostgreSQL também passou.

Ao vivo: coletor em `observe_only`, três horizontes por candle fechado,
lease PostgreSQL exclusivo e tarefa Windows `AgenteTrader-Timestral` em execução.
Na checagem das 12:05 UTC, havia nove previsões de três candles distintos.
Avaliações aguardavam o fechamento dos alvos, sem fabricar resultados.

## Replay causal e regressão operacional

Mesmo CSV de 1.500 candles normalizados UTC, mesmas configurações V4 e custos.
Não houve fine-tuning nem alteração de parâmetros. Holdout final reservado.

Plano Timestral: `validation-e664df57-3671-4926-ab08-16e476205575`.
Baseline: `validation-cb5d2e27-19e6-493b-89fd-655503e5921c`.

| Partição | Barras | Previsões | Avaliações | Decisões / execução |
|---|---:|---:|---:|---|
| Desenvolvimento | 900 | 207 | 206 | Digests idênticos ao baseline |
| Validação | 300 | 42 | 39 | Digests idênticos ao baseline |

Execuções Timestral: desenvolvimento `36bbea59-559e-4293-99e7-db02cb49e5ed`,
validação `c13ae1ab-e341-492f-89b9-c702b5db333b`.

Foram geradas 249 previsões e avaliadas 245. As quatro restantes não têm alvo
disponível dentro de sua partição. A falta de contexto, incluindo lacuna de fim
de semana, produziu `insufficient_data`, sem preencher candles artificialmente.

Resumo **descritivo combinado** das duas partições, sem uso para calibrar:

| Horizonte | Avaliadas | MAE Timestral (pips) | MAE constante | MAE drift | Direção | Cobertura Q10–Q90 |
|---|---:|---:|---:|---:|---:|---:|
| 15 min | 83 | 3,34 | 3,42 | 3,45 | 66,3% | 84,3% |
| 30 min | 82 | 5,38 | 5,41 | 5,61 | 57,3% | 76,8% |
| 60 min | 80 | 6,68 | 6,65 | 7,10 | 46,3% | 78,8% |

O modelo ficou próximo da previsão constante neste recorte e teve MAE maior
em 60 minutos. **Não há vantagem estatística ou econômica demonstrada.**
Não interpretar a tabela combinada como teste independente nem como taxa de
acerto operacional. São poucos períodos, com dependência temporal, regimes
limitados e corte de pré-treino externo não auditado. Não houve promoção ou
mudança na estratégia.

## Interface

Teste real com Chrome headless/Playwright contra a página publicada na VM:

- Gráfico e diagnóstico carregam três horizontes e o modelo verdadeiro.
- Alternância entre mercado ao vivo e replay exibe métricas separadas.
- Viewport móvel de 390 × 844 validado.
- Estado “Dados insuficientes” verificado com resposta de teste explícita.
- Zero exceções JavaScript capturadas.
- Sobreposição M5 de mediana e intervalo nominal conferida visualmente.

O painel usa as tecnologias existentes, sem substituição do gráfico. Os pontos
15/30/60 são ligados apenas para visualização, sem inferir valores intermediários.

## Testes automatizados

Com `TIMESTRAL_TEST_POSTGRES=1` e `TIMESTRAL_TEST_MODEL=1`, a suíte completa
passou com **118 testes, sem falhas ou testes ignorados**.
Ela
inclui o modelo real, testes do PostgreSQL e regressões anteriores. Os testes
Timestral cobrem falha/carregamento único, timeout com encerramento do processo,
limite de memória, formatos, dados ausentes, candles fechados, ausência de
informação futura, desativação sem chamadas ao banco/modelo, avaliação e ausência
de gateway de ordens. O holdout é bloqueado antes do processamento.

As versões e métricas acima são experimentais. O próximo passo é acumular
previsões realmente prospectivas e revisar erros/cobertura por regime e sessão
antes de considerar qualquer uso decisório.
