# Resultado do primeiro piloto EUR/USD — 22/10/2026

**Decisão: NOT_APPROVED. O Timestral-209M em operação foi preservado.**

Execução: `57c6293d-3033-4c63-b52b-055f3cd15f62`.
Dataset: `88c1896b75fffad9a9b1c377ab58eb5c9b51dd54932cf5142a2648cf2fa96fa5`.
Candidato 5M, SHA-256:
`cd86589546d21de70ae37d6012fb5c93402d9b895f00360b976ab8d4a2f9788b`.

## O que foi executado

- Exportação verificada de **74.520 candles M5** do PostgreSQL, com histórico
  congelado até 20/10/2026, 17:57 UTC. Não inclui o estudo de regimes reservado
  em 22/10. Treino: **3.179 janelas**; validação: **661**; teste: **705**.
- Treino real, em CPU, da saída do Timestral-5M. Backbone e pesos originais
  preservados. Três épocas; a validação da saída nativa escolheu a época 3.
- Exportação e recarga pelo SDK original com previsões exatamente iguais.
  Avaliação final pelo caminho público da inferência, com simetrização padrão.
- Replay causal de **22.501 candles**, incluindo 60 dias de aquecimento, e
  comparação secundária com **858 contextos exatos** arquivados do 209M.
- Pico observado da árvore de processos: **393 MB**. Nenhuma ordem enviada pelo
  laboratório. Agente e ponte não foram reiniciados para realizar o treino.

## Previsões no teste separado

| Horizonte | MAE 5M original | MAE 5M ajustado | MAE preço constante | Acerto direcional ajustado |
|---|---:|---:|---:|---:|
| 15 min | 2,706 pips | 2,704 pips | 2,664 pips | 49,79% |
| 30 min | 3,788 pips | 3,783 pips | 3,721 pips | 52,62% |
| 60 min | 5,331 pips | 5,325 pips | 5,255 pips | 50,92% |

Pinball médio dos 21 quantis: **1,329642 → 1,327736 pips**, melhora relativa de
**0,1433%**. Intervalo de 95% por reamostragem de 37 dias:
**0,054% a 0,227%**. Na validação, melhora de 0,1701%.

A melhora foi pequena e ficou abaixo do mínimo de **2%**, registrado antes do
treino. A cobertura Q10–Q90 do candidato ficou entre 79,01% e 80,71%, mas seu
erro de previsão da mediana não superou a referência de preço constante.
Essas métricas não demonstram vantagem operacional nem lucratividade.

O controle arquivado do 209M utilizou somente entradas com hash idêntico, mesmo
SDK/configuração e alvos disponíveis no teste. Nessa amostra de conveniência,
seu MAE foi aproximadamente 3,470 / 5,055 / 6,914 pips, contra 3,540 / 5,168 /
7,060 do candidato 5M. Essa amostra tem composição diferente do teste uniforme
da tabela; não comparar os valores entre as duas amostras. O controle não foi
usado para escolher a época ou alterar parâmetros.

## Entradas simuladas

Período avaliado: 31/08 a 20/10. Mesmas regras atuais de pullback, alinhamento
confirmado H4/H1, regime TREND, lote 0,01, risco e custos de simulação existentes.
**Zero entradas elegíveis nas duas versões**, portanto zero trades encerrados.

Bloqueios registrados nos ciclos avaliados:

- 7.698: regime exigido pela política não confirmado.
- 2.698: contexto diário insuficiente após aquecimento/reset por lacunas.
- 12: aguardando gatilho de pullback.
- 12: confirmação de tendência insuficiente.

O resultado financeiro é **inconclusivo**, não uma taxa de acerto de 0% e não
uma estratégia sem perdas. Não foram flexibilizadas as regras para fabricar
entradas. Esse teste é da hipótese fixa de pullback com previsão, não de toda
a seleção contextual adaptativa do agente.

## Decisão e próximos experimentos

Falharam os critérios `PINBALL_IMPROVEMENT_BELOW_2_PERCENT`,
`FINANCIAL_SAMPLE_INSUFFICIENT` e `NET_PROFIT_NOT_POSITIVE`.
A tentativa explícita de ativar este candidato foi recusada antes de modificar
a configuração. Ativação e rollback foram exercitados com arquivos temporários.

Não foi iniciado um estudo futuro para promover um candidato que já falhou na
triagem retrospectiva. O próximo experimento deve registrar outra hipótese,
preservar dados novos para validação e avaliar se o ganho compensa o custo de
treino. Separadamente, a limitação de entradas deve continuar sendo investigada
no estudo de regimes já existente; não é corrigida aumentando épocas do modelo.

Houve duas correções técnicas na execução: o carregamento offline foi limitado
aos arquivos efetivamente baixados e a avaliação final foi alinhada ao método
público de inferência. O candidato selecionado permaneceu congelado; nenhum
ajuste de hiperparâmetros foi escolhido a partir dos resultados do teste.
Os relatórios da saída nativa foram preservados separadamente dos finais.

Consulte o [painel](http://192.168.97.221:8097/treinamento) e o
[manual do laboratório](LABORATORIO_TIMESTRAL.md). Artefatos completos em
`data/training/runs/57c6293d-3033-4c63-b52b-055f3cd15f62/`, fora do Git;
manifestos, progresso e resultados no PostgreSQL.
