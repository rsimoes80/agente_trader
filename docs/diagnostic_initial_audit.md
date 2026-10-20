# Auditoria inicial do diagnóstico — 20/10/2026

Execução de desenvolvimento: `8c09f518-0caf-491d-911b-4a7f1574ccfd`. Dataset `a6f4979a0e0be077d120611fb93f6dad51b217612cb2488683162a82ca7d3b6a`. Contexto M30, execução M5; 900 observações. Não há avaliação financeira nesta comparação.

## Bloqueios registrados

| Motivo | Observações |
| --- | ---: |
| SESSION_NOT_AUTHORIZED | 360 |
| REGIME_UNKNOWN | 336 |
| REGIME_MISMATCH | 204 |

O motivo é o primeiro bloqueio registrado na ordem dos gates. Um regime UNKNOWN fora da sessão pode aparecer em SESSION_NOT_AUTHORIZED; a contagem por motivo não equivale à distribuição total dos regimes. Nenhuma hipótese chegou a autorização nesta amostra.

## Sensibilidade à janela de contexto

| Janela M30 | UNKNOWN | Mudanças / 100 atualizações M30 | Concordância baseline |
| ---: | ---: | ---: | ---: |
| 20 | 54.0% | 8.72 | 100.0% |
| 16 | 46.4% | 9.40 | 91.8% |
| 24 | 28.0% | 8.72 | 46.0% |

A janela 24 reduz UNKNOWN nesta amostra, mas sua concordância com o baseline é de apenas 46%. Isso evidencia sensibilidade dos rótulos; não demonstra melhora. Nenhum parâmetro foi promovido. O próximo insumo necessário é a revisão humana das classificações e dos casos divergentes.

Job persistido: `f68e6054-497e-4ba4-b503-85bc3b7f03ee`. Validação acessada: false. Holdout acessado: false. Aprovação automática: false.

Observações são candles correlacionados, não trades independentes. As revisões do painel são informadas e não medem acurácia independente.
