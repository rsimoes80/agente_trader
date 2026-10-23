# Entradas M1 com contextos M15/M10 e M10/M5

## Pergunta e interpretação

Períodos menores podem reagir mais cedo a movimentos intradiários, mas isso
não comprova maior acerto ou lucro após custos. H1/H4 também podem orientar
day trade: o horizonte do contexto e a duração da posição são coisas distintas.
M15 e M10 se sobrepõem e não constituem duas evidências independentes.

Foram consultadas novamente seções de Pring (páginas PDF 68–69) sobre
suporte/resistência e do Manual do Pullback (10 e 13) sobre estrutura preservada
e reteste de região anterior. O manifesto
`data/knowledge/literature_families.json` identifica as referências locais.
EMA, ATR, períodos e limiares deste estudo são definições de engenharia,
não uma receita numérica atribuída aos autores.

## Protocolos registrados antes dos resultados

ID: `4b39756aa50c48dde15f7a1cf8b9798885f2851e14ee999e0d6182060ea1d0fe`.

Esse primeiro protocolo exige agregações completas a partir de M1 e serve como
comparação conservadora. A auditoria posterior dos dados encontrou 232
intervalos com minutos ausentes, dos quais muitos ocorrem na virada diária;
isso pode impedir desproporcionalmente o aquecimento H4/H1 quando todo o
contexto é reiniciado por uma lacuna M1.

**Antes de qualquer seleção financeira**, foi registrado o protocolo primário
com contextos nativos do MT5:
`35520ecaa695eda4130c93568303fbe38e1476cb23ab35c98cf6fbca06275736`.
Ele usa os mesmos quatro perfis, regras e amostra de execução M1, mas busca
M5/M10/M15/H1/H4 diretamente do terminal, com 30 dias adicionais de contexto.
Um minuto sem candle não é preenchido: o OHLC maior é o publicado pela corretora,
que não estabelece uma trajetória intrabar completa. Ausência de um candle
inteiro do contexto invalida seus 60 candles de direção; contexto atrasado e
gatilho M1 com lacunas também bloqueiam sinais.

Uma versão preliminar, `856af733…`, teve apenas a captura executada e foi
substituída antes de gerar sinais/resultados: a versão atual trata a mudança de
alinhamento H4 por horário de verão durante o fim de semana fechado. Lacunas
de negociação continuam inválidas. O mesmo snapshot nativo foi reutilizado e
a alteração está registrada em `agent_m1_native_protocol_amendment`.

Os dois resultados serão preservados. A versão nativa responde à comparação
de períodos vista no MT5; a versão agregada mede a sensibilidade à exigência de
minutos completos. Essa ampliação foi motivada por qualidade dos dados, não
pela escolha de um resultado mais lucrativo.

| Perfil | Direção e confirmação | Gatilho |
|---|---|---|
| Hipótese A | M15 e M10 alinhados | M1 |
| Hipótese B | M10 e M5 alinhados | M1 |
| Controle de contexto | H4 e H1 alinhados | M1 |
| Controle de resolução | H4 e H1 alinhados | M5 |

Cada perfil possui duas carteiras separadas: pullback com retomada e
rompimento com reteste. Compra exige direção positiva em ambos os contextos;
venda exige direção negativa em ambos. Conflito ou contexto indefinido bloqueiam.
Os controles usam a mesma definição EMA20/50 e inclinação de três barras;
não são uma reprodução exata do classificador estrutural em produção.

### Execução e risco

- Todos executam no próximo open **M1 real**, inclusive o controle de gatilho M5.
- Limite comum de 60 minutos por posição, encerramento de sessão e margem de
  cinco minutos antes do fechamento. Nenhuma posição planejada para o dia seguinte.
- Lote 0,01, capital simulado USD 10.000 e limites de risco existentes:
  0,5% por operação, 2% diário, 5% de drawdown, cinco entradas/dia,
  spread máximo de dois pips e relação retorno/risco líquida mínima de dois.
- Stop estrutural, distância mínima de um ATR14 e alvo de três riscos,
  considerando a estimativa de spread e slippage na formulação do alvo.
- Spread histórico M1, slippage de 0,2 pip por execução a mercado e comissão
  hipotética USD 35/milhão por lado. Estresse: spread ×1,5 e slippage 0,4 pip.
- Comissão zero é apenas uma análise pareada de sensibilidade; não escolhe a
  vencedora nem comprova a tarifa futura da conta.
- Se stop e alvo são tocados no mesmo candle, assume-se stop primeiro.
  OHLC M1 não substitui ticks nem reproduz toda a execução da corretora.
- Lacunas inesperadas reiniciam o contexto; exposição sem dados é censurada,
  com resultado total desconhecido. Não há interpolação de preços.

## Dados e separação temporal

Foram capturados 499.999 candles M1 nativos do mesmo MT5, aproximadamente
junho/2025–outubro/2026. O snapshot bruto possui hash e o arquivo normalizado
é congelado no PostgreSQL. O relógio usa o perfil histórico previamente
verificado da corretora, com offset por data; isso não valida uma cotação ao vivo.

1. Desenvolvimento: após sete dias iniciais, até 31/12/2025.
2. Verificação: janeiro–junho/2026.
3. Verificação final histórica: julho/2026 até o encerramento da captura.

Todos os perfis compartilham o mesmo aquecimento e períodos. Contextos mais
longos ainda precisam atingir 60 candles fechados após início ou reinício por
lacuna. A janela final não é evidência prospectiva independente: esses preços
já foram pesquisados em resoluções mais altas.

Escolha somente no desenvolvimento, entre as hipóteses A/B: pelo menos
50 operações encerradas, lucro líquido positivo, fator de lucro ≥1,1,
resultado positivo no estresse e carteira sem exposição não resolvida.
Maior expectativa líquida escolhe a candidata. Se nenhuma passar, não há
vencedora. Antes das verificações, a escolha fica registrada e congelada.
Cada verificação exige pelo menos 20 operações e os mesmos critérios financeiros.
Os resultados de todos os perfis são preservados, inclusive perdas e censuras.

## Verificações já executadas

- 61 testes automatizados passaram, incluindo dez novos testes específicos M1,
  duração real de 60 minutos e invariância dos sinais ao acrescentar dados futuros.
- Cinco testes adicionais verificam os contextos nativos, ausência de dados
  futuros, horário de verão e bloqueios por contexto incompleto/atrasado e por lacunas M1.
- Três testes do auditor detectam alteração de custos, exposição desconhecida,
  contexto futuro e mudança de fonte, além de reconciliar os resultados pareados.
- Amostra nativa: 100 candles por período M5/M10/M15, todos coincidentes em
  OHLC e volume com a agregação dos M1. O spread agregado não foi equiparado
  ao campo spread nativo de outro período, pois a amostragem pode diferir.
- Protocolo, captura, arquivo normalizado, sinais, seleção e relatório são
  registros separados e auditáveis no PostgreSQL.

## Reprodução

```powershell
.venv/Scripts/python.exe run_m1_context_experiment.py --capture-only
.venv/Scripts/python.exe run_m1_context_experiment.py --resume PROTOCOL_ID
.venv/Scripts/python.exe run_m1_native_context_experiment.py --capture-only
.venv/Scripts/python.exe run_m1_native_context_experiment.py --resume NATIVE_PROTOCOL_ID
```

`--resume` exige os mesmos hashes de implementação e reutiliza o snapshot,
não busca um novo período. O `.npy` bruto fica em `data/reports/`, fora do Git;
replicação exige preservar esse arquivo e o backup PostgreSQL. O arquivo normalizado
também é verificado por hash antes do replay.

Este estudo não altera o agente em produção, envia ordens nem treina os pesos
do Timestral. Uma eventual aprovação histórica ainda exigiria avaliação futura.

## Resultados

### Checagem conservadora concluída

Relatório PostgreSQL `agent_m1_context_experiment`:
`cad0945c77a3f307ca46e7757096d73f3312de7f514c1a3c99a663973402e9f8`.

Cada célula mostra **operações encerradas / resultado líquido em USD**, no
cenário normal, lote 0,01. São carteiras separadas por perfil e período.

| Contexto e gatilho M1 | Desenvolvimento 2025 | Jan–jun/2026 | Jul–out/2026 |
|---|---:|---:|---:|
| M15/M10 — pullback | 641 / −156,09 | 639 / −123,82 | 395 / −103,90 |
| M15/M10 — rompimento/reteste | 327 / −56,96 | 378 / −76,31 | 168 / −34,85 |
| M10/M5 — pullback | 655 / −150,77 | 640 / −131,76 | 415 / −87,73 |
| M10/M5 — rompimento/reteste | 465 / −105,33 | 442 / −87,86 | 220 / −45,68 |

Nenhuma candidata passou no desenvolvimento; a seleção foi congelada como
`null` antes das verificações. As quatro regras também tiveram resultado normal
negativo nos dois períodos seguintes. A sensibilidade com comissão zero manteve
perdas nessas quatro regras nos três períodos; spread e slippage continuam cobrados.

O custo médio foi aproximadamente **2,19–2,21 pips por operação**. Por exemplo,
M15/M10 com rompimento/reteste teve expectativa bruta de 0,44 pip no
desenvolvimento e custo médio de 2,19 pips. A mediana das durações ficou entre
7 e 18 minutos, conforme perfil e período: são efetivamente entradas curtas.

![Expectativa bruta, custos e expectativa líquida no desenvolvimento conservador](audits/m1-conservative-costs.png)

Algumas carteiras sob estresse tiveram exposição censurada por lacuna e seu
resultado total é indeterminado (`null`), sem substituição por zero nem soma
de parcelas conhecidas como resultado completo. A frequência comparativa H4/H1
será avaliada na versão nativa; o aquecimento insuficiente desse controle limita
a comparação na versão conservadora.

A auditoria verificou 96 arquivos declarados de implementação, 63.069 sinais,
96 carteiras e 20.559 resultados encerrados **pareados**, incluindo cenários de
custos do mesmo sinal. Essa contagem não representa 20.559 experiências
independentes. Custos, saldo, duração de até 60 minutos, vínculo ao sinal,
direção e ausência de contexto futuro foram conferidos. A dependência de
seleção/estatística também coincide com o hash do estudo anterior selado.

### Comparação principal com contextos nativos

O replay do protocolo `35520ec…` está em andamento. A conclusão final sobre
as hipóteses aguarda esse resultado. O resultado conservador não demonstra
superioridade universal de H4/H1 nem justifica ativar uma nova regra.

### Auditoria reproduzível

```powershell
.venv/Scripts/python.exe verify_m1_context_results.py cad0945c77a3f307ca46e7757096d73f3312de7f514c1a3c99a663973402e9f8
# Quando o relatório nativo estiver disponível:
.venv/Scripts/python.exe verify_m1_context_results.py NATIVE_REPORT_ID --native
```

O auditor lê registros selados e preserva seu resultado no PostgreSQL como
`agent_m1_context_verification`. Os relatórios completos ficam em `data/reports/`.
