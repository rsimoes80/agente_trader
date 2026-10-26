# O que as previsões Timestral acrescentam — 26/10/2026

## 1. Auditoria das previsões existentes

Foram lidos 7.344 caches do Timestral 209M original. Excluíram-se 18 entradas
fora da cobertura da fonte congelada e duas duplicatas da mesma referência.
Sete horizontes futuros não tinham cobertura para avaliação. Todos os demais
prefixos foram conferidos contra seu hash de candles: nenhuma divergência.

O protocolo foi registrado antes de calcular as métricas. Somente candles
fechados anteriores à previsão entram nos baselines. Desenvolvimento e checagem
são separados em julho/2026, com descarte de rótulos que cruzem a fronteira.
Modelos e configurações nunca são agrupados juntos. A amostra é de caches
irregulares, influenciada pelos sinais que geraram previsões; não representa
amostragem uniforme de todo o mercado nem dados prospectivos inéditos.

### Checagem de julho a outubro/2026

| Horizonte | Casos | MAE modelo (pips) | MAE preço atual (pips) | Direção, sem movimentos nulos | Cobertura Q10–Q90 |
|---|---:|---:|---:|---:|---:|
| 15 min | 2.379 | 3,205 | 3,189 | 52,75% | 78,86% |
| 30 min | 2.378 | 4,496 | 4,468 | 52,48% | 79,02% |
| 60 min | 2.373 | 6,303 | 6,265 | 52,58% | 79,22% |

Os intervalos descritivos da diferença pareada de MAE, obtidos por bootstrap de
semanas UTC, incluem zero nos três horizontes da checagem. Não se demonstrou
vantagem da mediana para decidir entradas. Em 30 minutos, o deslocamento mediano
absoluto previsto foi 0,417 pip, contra cerca de 2,219 pips de custos assumidos.
Isso não é um erro por si só: a mediana pode ser próxima do preço atual enquanto
a distribuição prevê grande incerteza. Também não equivale a lucro esperado.

### Intervalos e baseline probabilístico

Uma previsão de intervalos não deve ser comparada apenas com uma previsão pontual
sem dispersão. Por isso foi incluído um baseline empírico: Q10/Q50/Q90 dos
deslocamentos históricos do mesmo horizonte no prefixo exato usado pelo modelo.

| Horizonte, checagem | Pinball Timestral (pips) | Pinball empírico (pips) | Cobertura empírica |
|---|---:|---:|---:|
| 15 min | 1,0543 | 1,0942 | 67,68% |
| 30 min | 1,4945 | 1,5556 | 67,70% |
| 60 min | 2,1295 | 2,2300 | 67,09% |

Menor pinball é melhor. O Timestral superou esse baseline em desenvolvimento
e checagem nos três horizontes; os intervalos semanais descritivos da diferença
foram positivos. Não há ajuste por múltiplas comparações, prova de independência
ou demonstração de lucro de carteira. A evidência favorece estudar sua utilidade
para incerteza; ela não autoriza transformar a direção da mediana em ordem.

Reprodução: `python run_forecast_diagnostics.py`.
Relatório PostgreSQL `agent_forecast_information_audit`:
`92baa0425a74d14fb50a3c3da76d816ec7fb9ebb60cc7dc402a70d9aa061d63c`.
Nove testes puros verificam hashes, fronteira temporal, gaps, deduplicação,
separação de modelos e bootstrap.

## 2. Prova pequena em M5, M15 e H1

Uma hipótese separada comparou o mesmo **Timestral 5M original**, com contexto de
64 barras, nos três timeframes. Não é comparação direta de tamanho com o 209M:
o controle M5 também usa 5M, para isolar o efeito do timeframe neste teste.

Regras congeladas: decisão às 09:00 de Londres nos dias úteis, com horário de
verão; entrada na abertura M5 seguinte; direção da mediana de seis barras;
stop 1,5 ATR e alvo 3R; prazo de seis barras do timeframe, gerenciado em M5;
custos e limites de risco existentes. Os braços com filtro exigem deslocamento
mediano maior que o custo estimado. Não houve treino ou mudança de pesos.

| Timeframe / regra | Desenvolvimento: operações / líquido USD | Checagem: operações / líquido USD |
|---|---:|---:|
| M5, direção | 92 / −9,94 | 43 / −9,97 |
| M5, direção e custo | 15 / +1,42 | 2 / −1,26 |
| M15, direção | 147 / −10,23 | 59 / −10,10 |
| M15, direção e custo | 43 / +4,20 | 16 / −4,21 |
| H1, direção | 151 / −49,15 | 76 / −20,00 |
| H1, direção e custo | 62 / +1,74 | 30 / −9,72 |

Nenhuma candidata cumpriu os critérios fixados de amostra e fator de lucro no
desenvolvimento. Os pequenos ganhos iniciais não se mantiveram na checagem.
Não houve selecionada, ativação ou ordens enviadas. Os 699 contextos e previsões
foram persistidos, permitindo reproduzir sem novas inferências.

Reprodução: `python run_timestral_timeframe_pilot.py --resume 4aa0396821ce6a541a46344e566829f16ec5fdca7d3050ea944d6bef940efd4b`.
Relatório PostgreSQL `agent_tf_model_experiment`:
`3223000c50eba065f52e11dbf564fe9fa7dc8298d90a53aa55c0f6dee8ad6f22`.
Quatro testes cobrem o filtro econômico, os níveis de saída, os dados ausentes
e a agenda com horário de verão. A configuração operacional M5 foi preservada.
