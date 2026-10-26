# Evolução para múltiplos ativos

## Objetivo integral

Permitir escolher os símbolos disponíveis no MT5, configurar lote por ativo e
executar análises e operações simultâneas. Cada ativo deve ter contexto,
experiências, hipóteses, resultados e modelos ajustados próprios. A conta mantém
limites conjuntos de risco e margem. O projeto continua exclusivamente em demo.

## Sequência e estado

1. **Contratos e dados — base implementada.** Catálogo por nome exato, inspeção
   financeira usando `order_calc_profit`, arquivos históricos separados por
   símbolo e unidade de preço própria. A ponte deixa de substituir silenciosamente
   todo pedido de gráfico por EURUSD. As novas rotas continuam autenticadas pela ponte.
2. **Configuração e controles implementados; novos ciclos ainda pendentes.**
   Seletor no painel, lote persistente por ativo, estados e comandos independentes,
   contratos verificados pela ponte, gráficos e diagnósticos identificados pelo
   símbolo. A sessão EURUSD legada conserva suas chaves. Ainda falta o coordenador
   iniciar e retomar os ciclos de análise dos demais ativos. Enquanto isso, o painel
   informa a preparação pendente e bloqueia o botão de início desses ciclos.
3. **Contratos de pesquisa parametrizados; ciclo integrado ainda pendente.**
   Perfis explícitos já parametrizam a leitura técnica, unidades, limite de spread,
   calendário semanal, custos e simulador. Ainda falta integrar memória, revisão,
   treinamento e coordenação contínua por ativo. Compartilhar
   a inferência do Timestral e manter um treinamento pesado por vez. Não transferir
   resultados ou modelos ajustados de EURUSD para XAUUSD como se fossem equivalentes.
4. **Risco e execução conjunta — pendente.** Substituir o bloqueio de toda posição
   da conta por controles por símbolo e risco agregado. Manter o journal de envio
   serializado, reconciliação de ordens incertas e veto a conta real. Tratar posições
   externas, ordens pendentes, margens e perdas diárias uma única vez na conta.
5. **Validação e liberação — pendente.** Simulação, testes de dois símbolos ao mesmo
   tempo, reinício, suspensão e reconciliação, com custos próprios. Só depois
   habilitar os novos ciclos demo; hipóteses sem confirmação continuam em espera.

O objetivo permanece incompleto enquanto os itens 2–5 não forem comprovados.
Os contratos de outros ativos não estão liberados para execução pelo motor legado.

## Evidência da inspeção no terminal

ThinkMarkets-Demo, conta em USD:

| Símbolo exato | Contrato informado | Lote mínimo | Tick de preço |
| --- | ---: | ---: | ---: |
| EURUSD | 100.000 | 0,01 | 0,00001 |
| XAUUSD | 100 | 0,01 | 0,01 |
| XAUUSD247 | 10 | 0,01 | 0,01 |

XAUUSD e XAUUSD247 são instrumentos diferentes. A descrição ou prefixo não
autoriza substituir um pelo outro. No teste nativo, uma variação de preço de
US$ 1 em XAUUSD com lote 0,01 produziu cálculo de US$ 1 de resultado. Isso é
inspeção de contrato, não uma operação enviada nem garantia de custo de execução.
Comissão não é presumida como zero quando não está disponível nesse endpoint.

Foram importados 30 dias de XAUUSD em M1/M5/M15/M30/H1/H4/D1. Baseline inicial:
`7ce3ba5bf318ece2f5d1aedba790836aa47e5ab9fb7c818441360ed7020489d3`,
com 5.762 candles M5 fechados conferidos contra seu hash. A cobertura passou na
convenção semanal atual de 95%; o calendário específico do metal ainda precisa
ser integrado à análise e aos testes. Essa cobertura não libera ordens.

## Isolamento e compatibilidade

Candles usam chave composta por fonte, símbolo e período. Baselines e estudos
de símbolos novos usam tipos de registro próprios, como
`historical_baseline:XAUUSD`; leitores antigos do EURUSD não os escolhem como
se fossem sua baseline mais recente. Registros legados sem `symbol` continuam
pertencendo ao EURUSD. Nenhum histórico existente foi apagado.

A unidade `price_unit` acompanha a baseline. Estatísticas de amplitude usam essa
unidade, sem dividir preços do ouro pelo pip do EURUSD. O executor, os custos e
os treinos ainda precisam receber a mesma parametrização antes da ativação.

Rotas somente leitura: `/api/mt5/instruments?q=XAU` e
`/api/mt5/instrument?symbol=XAUUSD`. A segunda verifica o nome exato e calcula
sondas financeiras pelo SDK; não chama `order_send`.

## Configuração e interface

`AssetRegistry` grava `asset_configuration` e audita comandos idempotentes. O
cliente informa apenas símbolo e lote; o servidor busca o contrato na ponte.
Remover ou alterar o lote de um ativo em execução é recusado. O lote efetivamente
usado ao iniciar é lembrado, sem permitir que uma resposta de sessão antiga
sobrescreva uma configuração posterior.

`OperationControl(memory, symbol)` separa estados, comandos, gerações e sinais
de atividade por ativo. A trava de comandos continua conjunta; ela não autoriza
enviar duas ordens nem substitui a futura reserva de risco agregado. Consultar
XAUUSD não pausa, retoma ou redefine a sessão EURUSD.

A página aceita `?symbol=XAUUSD`, usa cache de gráfico por ativo e confere o
símbolo retornado pela API antes de mostrar dados ou habilitar controles. As
previsões do EURUSD são explicitamente excluídas dos gráficos de outros ativos.
O selo de execução de novos símbolos dependerá de um serviço multiativo válido;
configurar um símbolo no catálogo não concede autorização de envio.

## Perfis de pesquisa por instrumento

`InstrumentResearchProfile` identifica contrato, moeda da conta, unidade de preço,
limite de spread, calendário e custos. Seu hash muda quando qualquer um desses
insumos muda. O calendário declara intervalos semanais, fuso, versão e fonte;
lacunas no histórico não criam automaticamente feriados ou pausas autorizadas.
O perfil pode ser serializado e reconstituído com conferência do hash.

As funções de leitura técnica, proposta de pullback, cache Timestral e simulação
aceitam esse perfil. Cache e identificadores de experiências incluem sua identidade.
Simulações novas expressam quantidade em **lotes**, com valor financeiro por lote
e comissão por lote/lado explicitamente declarados. Um checkpoint de ouro não pode
ser retomado no simulador legado do euro, com outro contrato, lote ou custo.
Os caminhos legados sem perfil preservam as convenções e chaves do EURUSD.

Custos desconhecidos impedem a simulação financeira; não se tornam comissão zero.
A valorização histórica atual suporta apenas os modelos lineares Forex/CFD cujo
lucro já é expresso na moeda da conta e cujo valor por preço confere com o contrato.
Conversões históricas, modelos inversos e futuros exigem implementação específica.
Uma sonda financeira atual do MT5 não demonstra uma conversão constante no passado.
Faixas de volatilidade também precisam ser calibradas por ativo: sem faixas
declaradas, o contexto fica sem essa classificação, sem reutilizar cortes do euro.

Essa infraestrutura ainda **não liga o XAUUSD ao aprendizado contínuo nem à execução**.
O portfólio legado recusa propostas de outro instrumento. A integração do ciclo
completo, a revisão de hipóteses, os treinos e os limites agregados permanecem
necessários antes da liberação no painel.

Referência de horários: [especificações da corretora](https://www.thinkmarkets.com/en/contract-specifications/).
O calendário efetivo deve ser conferido com o contrato e os dados da conta utilizada;
o calendário Forex não é presumido como calendário do ouro ou de outros mercados.

## Conferência da interface publicada

Em 26/10/2026, a conferência em Chrome isolado verificou EURUSD e XAUUSD no seletor,
cotações próprias em ambas as telas, bloqueio explícito do início do XAUUSD e
ausência de erros JavaScript ou transbordamento horizontal na largura de 390 px.
Nenhum comando operacional ou ordem foi enviado nessa conferência. O EURUSD
permaneceu na sessão existente. As evidências locais ficam em
`.tools/asset-selector-browser-verification.json` e capturas correspondentes.
