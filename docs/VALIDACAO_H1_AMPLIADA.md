# Validação ampliada da candidata H1

## Objetivo e funcionamento

Verificar se o rompimento com reteste em H1 apresenta vantagem líquida em
períodos adicionais e em observação futura. O resultado positivo de 2026 motivou
esta investigação; ele não é uma promessa de rentabilidade.

Foram mantidos o contexto H4, os parâmetros de EMA/ATR/reteste, alvo de 3R,
lote de 0,01, risco, limite de spread e encerramento cinco minutos antes do fim
da sessão. As entradas e saídas usam preços M5 originais. H4 como contexto e
confirmação representa informação correlacionada, não duas confirmações independentes.

## Etapas implementadas

1. **Ampliar a fonte:** limite do terminal aumentado de 100 mil para 500 mil
   candles. Backup local de `config/common.ini` preservado no diretório do MT5.
   Reinício gracioso feito em conta demo sem posições nem ordens abertas.
2. **Congelar dados:** captura MT5 imutável, hash SHA-256, normalização UTC por
   data e arquivo de candles no PostgreSQL. Cinco anos completos, 2021–2025,
   com 30 dias adicionais de aquecimento em cada janela.
3. **Testar regras fixas:** carteira anual, carteira conjunta, custos agravados,
   tamanho da amostra, censura de exposição e concentração do lucro.
4. **Observar preços novos:** tarefa independente `AgenteTrader-H1Shadow`,
   exclusivamente em simulação, com persistência e retomada no PostgreSQL.
5. **Decidir com evidências:** nenhum resultado deste processo ativa uma
   estratégia na corretora ou altera os pesos do Timestral automaticamente.

O agente principal permaneceu na mesma sessão durante o trabalho.

## Protocolo e critérios

Protocolo registrado antes dos resultados adicionais:
`4865501c4118d37fbd53f9872e3040565a637c1e3c9d978f3a3be7016fb12f53`.

- 2021–2023 em carteira conjunta: pelo menos 50 operações encerradas, lucro
  líquido positivo, fator de lucro ≥ 1,1 e resultado positivo sob estresse.
- 2024 e 2025 separadamente: pelo menos 20 operações por ano e os mesmos critérios.
- Carteiras sem exposição censurada, bloqueio da conta ou posição pendente.
- Cobertura e limitações da fonte publicadas, sem inventar candles ausentes.

A carteira conjunta é simulada novamente; não é apenas a soma de carteiras
anuais reiniciadas. Cada janela tem uma exclusão de novas entradas nas últimas
24 horas para evitar posições atravessando seu limite.

Custos: spread histórico observado, slippage de 0,2 pip e comissão assumida de
US$ 35 por milhão por lado. A comissão ainda não é uma tarifa confirmada da
corretora. Estresse: spread × 1,5 e slippage de 0,4 pip, mantendo os alvos
originais. Vetos de risco podem alterar quais operações são executadas no estresse.

Esses anos fornecem corroboração histórica adicional. Não são validação
prospectiva: a candidata já foi selecionada após pesquisar 2026, e o final de
2025 pode se sobrepor a pesquisas anteriores. Os mínimos de operações não
provam vantagem sozinhos. Nenhum limite foi reduzido após ver os resultados.

## Observação contínua

Início prospectivo: **23/10/2026 às 13:35 de Brasília** (16:35 UTC).
Protocolo do observador:
`ee64b0a467c7ba7908178d90c99f3c5ea442600432cc7480dec2f7b95ca90aed`.

O observador consulta candles fechados a cada 30 segundos e mantém:

- Contexto inicial congelado e candles posteriores com horário da primeira captura.
- Sinais H1, entradas simuladas e resultados normais e sob estresse.
- Sinais atrasados identificados separadamente e excluídos das entradas prospectivas.
- Lacunas e posições censuradas preservadas, sem reiniciar a carteira para esconder perdas.

Um sinal só é considerado acompanhado no prazo se o candle que o confirmou
foi capturado em até 90 segundos após seu fechamento. As entradas usam a abertura
M5 seguinte e custos modelados; não são comprovantes de execução da corretora.
Uma posição simulada ainda aberta é normal durante o acompanhamento e não deve
ser confundida com uma operação encerrada.

O observador retoma o mesmo protocolo e arquivo após reinício, desde que o código
permaneça igual. Mudanças de código geram outra identidade de experimento.
Há trava de processo no PostgreSQL para impedir observadores duplicados.

Windows conectado, MT5 e PostgreSQL disponíveis são necessários para coletar
preços novos. O navegador pode ficar fechado. A tarefa inicia no login do Windows;
ela não funciona enquanto o computador estiver desligado. Falhas de conexão
geram novas tentativas; dados recebidos depois de uma interrupção não se tornam
retroativamente entradas prospectivas.

## Consultar e reproduzir

```powershell
.venv/Scripts/python.exe h1_research_status.py

# Retomar o teste congelado, sem recapturar nem alterar regras:
.venv/Scripts/python.exe run_h1_extended_validation.py --resume 4865501c4118d37fbd53f9872e3040565a637c1e3c9d978f3a3be7016fb12f53

# Consulta/coleta única; --watch mantém a execução:
.venv/Scripts/python.exe run_h1_shadow.py

# Instalação da tarefa em outro Windows preparado para o projeto:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install_h1_shadow_startup.ps1
```

Registros PostgreSQL: `agent_h1_extended_protocol`, `agent_h1_extended_capture`,
`agent_h1_extended_history`, `agent_h1_extended_signals`,
`agent_h1_extended_experiment` e `agent_h1_shadow_*`.
Captura bruta e relatórios completos ficam em `data/reports/`, fora do Git.
Para reproduzir o teste em outro equipamento, preserve também o arquivo
`h1-raw-*.npy` correspondente; o backup PostgreSQL contém os candles normalizados,
mas não o arquivo binário bruto solicitado pelo modo `--resume` deste runner.

Uma primeira tentativa foi interrompida antes de qualquer cálculo financeiro:
o hash havia sido calculado sem os metadados acrescentados pelo repositório.
O protocolo corrigido usa o mesmo arquivo bruto e verifica preços e metadados
antes de congelar os dados. A tentativa anterior permanece auditável pela chave
`6c5cf0040caf0a8d24e610fb79b04283a0a8ea05928a086ddcc191d14a354d35`.

## Resultados

**A candidata não foi aprovada.** O resultado favorável de 2026 não se manteve
de forma consistente na amostra ampliada.

| Ano | Operações encerradas | Líquido normal (US$) | Líquido sob estresse (US$) | Fator de lucro normal |
|---|---:|---:|---:|---:|
| 2021 | 30 | −11,09 | −13,69 | 0,61 |
| 2022 | 45 | +21,26 | +17,22 | 1,42 |
| 2023 | 59 | +12,03 | +7,32 | 1,28 |
| 2024 | 52 | −18,98 | −23,20 | 0,56 |
| 2025 | 21 antes do bloqueio | Indeterminado | Indeterminado | Não representa o ano completo |

A carteira conjunta 2021–2023 teve 134 operações, US$ 22,20 líquidos e fator
de lucro 1,18. Sob estresse, o lucro caiu para US$ 10,85. Esse bloco cumpriu
o critério registrado, mas 2024 falhou mesmo com amostra suficiente.

Em 2025, os candles de **05/09 às 16:25 e 16:30 UTC** estão ausentes enquanto
havia uma compra aberta desde 13:00 UTC. Uma consulta nova e direta
`copy_rates_range` confirmou a ausência. A carteira foi censurada ao observar
a próxima barra, às 16:40 UTC. O parcial das 21 operações encerradas é
**−US$ 15,82**, mas não é o resultado anual: a operação censurada e as entradas
posteriores não têm resultado de carteira completo. Não houve interpolação,
fechamento inventado nem alteração das regras para contornar essa lacuna.

Na carteira de cinco anos, houve 207 encerramentos observados e uma operação
censurada. O total líquido continua **indeterminado**. As métricas calculadas
sobre esses encerramentos, incluindo bootstrap e fator de lucro, descrevem
somente a parcela observada; não validam o total da carteira.

Como diagnóstico separado, a soma das quatro carteiras anuais completas
2021–2024 ficou em apenas **+US$ 3,22**. Retirar o melhor negócio transforma
essa soma em **−US$ 5,56**. Um bootstrap descritivo em blocos de dias com
operações apresentou faixa de 95% de aproximadamente **−US$ 59,24 a +US$ 67,17**.
Não é intervalo de lucro futuro, não elimina dependência entre dias ou o efeito
da seleção anterior da estratégia e não constitui teste independente.

Cobertura por ano, incluindo aquecimento: 99,17%, 99,56%, 98,82%, 98,81% e
98,83%. O indicador genérico `data_ready` ficou falso: em 2022 e 2023 a janela
termina após fechamento semanal e ultrapassa a exigência de frescor de seis
horas do resumo mensal. Essa limitação foi mantida explícita, sem apresentar
os cinco anos como arquivo perfeitamente completo. A lacuna de 2025 é um
problema adicional e concreto de exposição sem preço.

O controle de 2026 reproduziu **exatamente** os 47 sinais, as 29 operações e
US$ 21,73 líquidos do experimento anterior. Portanto, os anos negativos não
decorrem de uma mudança silenciosa na candidata.

**Conclusão:** há períodos favoráveis, mas ainda não há evidência suficiente
de uma vantagem consistente após custos. A candidata permanece em pesquisa.
A observação futura está funcionando e o agente principal não recebeu essa
estratégia. O próximo estudo deve explicar a diferença entre os contextos
favoráveis e desfavoráveis, com hipótese registrada e novos dados de avaliação;
escolher filtros apenas porque eliminam perdas passadas produziria sobreajuste.

Relatório PostgreSQL `agent_h1_extended_experiment`:
`50f2555e7fd9bef884744624196004bb0517992cdef16ad9d1853064a09288ff`.
Auditoria `agent_h1_extended_audit` e confirmação da lacuna
`agent_h1_extended_gap_check` usam a mesma chave.

72 testes direcionados aprovados. O observador gravou seu primeiro ciclo
prospectivo às **13:40:25 de Brasília**, com um candle novo, nenhum sinal H1
e nenhuma ordem enviada. A ausência de sinal nessa primeira barra é esperada.

## Referência da configuração MT5

A API disponibiliza o histórico permitido pela configuração do terminal:
[copy_rates_range — documentação oficial MQL5](https://www.mql5.com/pt/docs/python_metatrader5/mt5copyratesrange_py).
