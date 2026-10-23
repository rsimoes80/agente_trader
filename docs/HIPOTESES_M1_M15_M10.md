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

- 58 testes automatizados passaram, incluindo dez novos testes específicos M1,
  duração real de 60 minutos e invariância dos sinais ao acrescentar dados futuros.
- Cinco testes adicionais verificam os contextos nativos, ausência de dados
  futuros, horário de verão e bloqueios por contexto incompleto/atrasado e por lacunas M1.
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

O processamento completo está em andamento. Nenhuma conclusão de desempenho
foi tirada dos testes de integridade ou dos testes unitários.
