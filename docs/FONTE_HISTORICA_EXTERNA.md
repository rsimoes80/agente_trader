# Verificação de fonte histórica externa — 23/10/2026

## Objetivo

Verificar a viabilidade de testar a candidata M15 congelada em anos anteriores
a 2020, sem reutilizar os períodos já pesquisados e sem preencher lacunas do
MT5 com preços de outra corretora. Isso seria uma verificação entre fontes,
não uma validação prospectiva nem uma demonstração de lucro futuro.

## Resultado da verificação

A Dukascopy mantém um [exportador oficial de histórico](https://www.dukascopy.com/api/data/get/historical-data-export)
com preços bid/ask e volumes. A [documentação de exportação](https://www.dukascopy.com/wiki/en/development/data-export/)
também descreve acesso S3 com credenciais AWS e cobrança ao solicitante.
Esse caminho pago não foi utilizado.

Uma sondagem limitada do domínio público `datafeed.dukascopy.com` tentou obter
arquivos M1 bid e ask de EURUSD para 07/01/2019 e 08/01/2024. As quatro
requisições retornaram HTTP 429. Não houve novas tentativas após a sondagem.
Não foi possível confirmar o formato binário, a cobertura, os preços ou as
condições de uso desses arquivos; nenhum dado externo foi importado ou usado
em backtest. Resposta 429 não demonstra indisponibilidade permanente.

O registro técnico local está em
`data/reports/external-source-probe/probe.json`, fora do Git, e seu resumo
é preservado no PostgreSQL como `agent_external_source_probe`.

## Condições para avançar

1. Obter uma amostra por um canal autorizado e acessível.
2. Confirmar licença, UTC, escala de preço, OHLC, bid/ask e cobertura.
3. Registrar identidade da fonte e hashes em um conjunto separado do MT5.
4. Congelar previamente os períodos, a regra e os critérios de avaliação.
5. Modelar os custos da conta de destino; spread de outra corretora não
   representa automaticamente o spread da conta MT5.

Até isso ser possível, os observadores existentes continuam recolhendo dados
novos do MT5 para as comparações simuladas. A tentativa de fonte externa não
alterou regras de execução, parâmetros de risco ou pesos do Timestral.
