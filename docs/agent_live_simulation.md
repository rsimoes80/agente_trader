# Aprovação e simulação operacional

Status: implementadas no ramo `feat/agent-operational-cycle`, com testes
isolados de persistência, execução e interface. Publicação e validação com
uma versão aprovada a partir do mercado ainda pendentes. Nenhuma aprovação
sintética de teste é gravada na base de produção.

## Fluxo

1. Escolher o lote e iniciar. O serviço Windows prepara os 30 dias mensais.
2. Se existir aprovação compatível e vigente, reutilizar sua versão congelada.
   Caso contrário, executar a pesquisa histórica e apresentar o resultado.
3. Um relatório reprovado ou com amostra insuficiente bloqueia a operação.
   Um relatório validado apresenta **Aprovar esta versão para simulação**.
4. A aprovação autenticada vincula relatório, modelo, esquema de variáveis,
   configuração Timestral, fonte, lote e operador. Dura no máximo sete dias;
   a validação também não pode ter mais de sete dias. Não habilita ordens MT5.
5. Carregar contexto e analisar somente candles M5 fechados. O contexto e o
   setup técnico precisam ser elegíveis antes do filtro aprendido e do risco.
6. Se aprovar a oportunidade, consultar novamente a cotação e a intenção do
   operador. A cotação de entrada precisa ter no máximo cinco segundos; o
   sinal, no máximo 90 segundos. O lote não é reduzido para forçar aprovação.

Iniciar novamente não apaga o saldo, a maior equidade, os resultados ou o
número de entradas do dia da conta simulada. O saldo inicial de pesquisa é
USD 10.000; não representa saldo de corretora. Os limites são 0,5% por entrada,
2% de perda diária, 5% de drawdown e cinco entradas por dia.

## Preço e resultado

- Compra usa ask observado; venda usa bid observado. A saída usa o lado oposto.
- Slippage de pesquisa: 0,2 pip por execução; comissão: USD 35 por milhão de
  unidades, por lado. São hipóteses explícitas, não tarifas confirmadas da conta.
- Entrada é registrada no instante da observação, sem retroagir à abertura
  do candle. Stop e alvo permanecem nos níveis congelados da hipótese.
- A posição fecha no stop/alvo observado, após uma hora, ou por Parar.
- A consulta de cotações é periódica. Pode perder movimentos entre consultas;
  lacunas superiores a 30 segundos também marcam cobertura incerta. Nenhum
  resultado desse executor ganha automaticamente um rótulo confiável de treino
  (`learning_eligible=false`). É necessário validar a trajetória com dados
  mais finos antes de reutilizá-lo como resultado de mercado certificado.

## Pausa, parada e falhas

| Evento | Comportamento |
|---|---|
| Pausar | Bloqueia novas entradas; continua acompanhando posição existente |
| Parar | Fecha a posição simulada na próxima cotação válida e encerra |
| Fonte indisponível | Preserva posição/checkpoint; aguarda cotação válida |
| Aprovação expirada ou histórico indisponível | Bloqueia entradas e continua a gestão da posição |
| Reinício do serviço | Solicita revisão/retomada; reconcilia a posição persistida |
| Tentativa de iniciar outra sessão com posição | Recusa; não descarta a posição |
| Pausa durante inferência | A confirmação transacional impede a nova entrada |

Eventos, checkpoint, projeção da conta e estado são gravados na mesma transação
PostgreSQL. Há lease de serviço, dono da execução e geração de comando para
impedir que um processamento antigo abra uma posição após mudança de intenção.

## Leitura da tela

- **Preparação:** quantidade real de candles e hipóteses; hipótese ainda não é
  operação encerrada. Os 30 dias do produto e a janela maior de pesquisa são
  apresentados separadamente.
- **Última decisão:** motivo, horário, candle de referência e níveis. Quando
  houver inferência, apresenta estimativa do filtro e seu limiar de seleção.
- **Gráfico:** previsão Timestral da oportunidade, com referência e faixa nominal
  Q10–Q90, somente enquanto atual e da mesma fonte. Desaparece após o próximo
  fechamento M5, sem prolongar uma previsão antiga. Não é probabilidade de trade.
- **Posição e conta:** preço observado, resultado aberto estimado e encerrados.

O executor demo é uma entrega separada. O perfil atual continua `paper_only`;
conectar o terminal a uma conta demo não muda essa autorização.

## Evidências de verificação

- Testes PostgreSQL usam schema isolado e rollback; relatórios e modelos
  sintéticos não são promovidos para produção.
- Testes cobrem aprovação exata/idempotente, troca de lote, controle de dono,
  pausa concorrente, reinício, fonte ausente, Parar durante consulta e o ciclo
  completo de uma posição simulada com persistência de resultado.
- Handler HTTP real testado com cookie, CSRF, login e logout.
- Chrome em desktop/celular, com API interceptada, testa lote, autenticação,
  estado, fonte/validade da previsão e ausência de rolagem horizontal.
- Prévia somente leitura também conferida com estado real do PostgreSQL e
  cotações atuais do MT5, sem enviar comandos ao serviço em treinamento.
