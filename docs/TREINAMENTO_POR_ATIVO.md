# Retreinamento do Timestral por ativo

## O que é ajustado

O laboratório existente ajusta os pesos da camada de saída do **Timestral-5M**.
O restante da rede permanece congelado. Não é um treinamento completo do 209M
nem um treinamento dos livros: as referências orientam as regras técnicas e
as hipóteses; candles reais orientam o ajuste numérico da previsão.

EURUSD mantém seus registros anteriores. XAUUSD e novos perfis recebem filas,
dados, métricas, checkpoints, estudo prospectivo e configuração de modelo próprios.
O modelo pré-treinado pode ser comum, mas resultados e pesos ajustados não são
transferidos automaticamente entre ativos. A configuração é identificada pelo
nome exato do símbolo e hash do perfil financeiro/calendário.

## Fluxo automático

1. O serviço verifica os ativos selecionados com agente em execução.
2. Um novo ciclo exige 288 candles M5 novos e 24 horas desde a tentativa anterior.
   **Antecipar treino** pode solicitar um ciclo antes desse intervalo.
3. Uma fila por ativo persiste no PostgreSQL. Um lease global permite somente
   um treinamento pesado de cada vez; aguardar validação prospectiva não ocupa
   essa vaga. Adiar por recursos permite que outros trabalhos elegíveis avancem.
4. Para um novo perfil, o laboratório busca até 365 dias M5 disponíveis no MT5,
   importa os candles para o arquivo PostgreSQL e congela um dataset separado da
   baseline operacional de 30 dias. Menos histórico pode ser aceito somente se
   houver amostra mínima; dados ausentes não são fabricados.
5. O treino usa divisão cronológica 70/15/15, com pelo menos 200 janelas por
   partição, alvos sem cruzar fronteiras e contexto exclusivamente passado.
6. Treina somente a saída, escolhe a época pela validação, congela o candidato
   e avalia o teste pelo SDK público. Checkpoints permitem retomar etapas salvas.
7. Se a previsão passar, compara original/ajustado em replay com lote 0,01,
   custos e calendário do próprio perfil. A conta demo não recebe essas ordens.
8. Um candidato elegível passa por comparação prospectiva com a base e o modelo
   ativo, usando preços observados posteriormente e carteiras simuladas separadas.
9. Somente após todos os critérios a configuração daquele ativo/perfil é
   atualizada. O agente recarrega os pesos quando não possui posição ou envio
   pendente. Uma mudança do modelo de referência invalida a comparação em curso.

Os critérios incluem melhora mínima de 2% na perda quantílica, evidência pareada
por dia, limites de degradação de erro/direção e cobertura dos intervalos. A etapa
financeira exige resultado líquido positivo, pelo menos 20 operações por braço
e drawdown não superior ao original. A etapa futura exige ao menos sete dias
corridos, **20 dias distintos**, 200 previsões avaliadas, 20 operações por braço
e ausência de cobertura incerta. Portanto, sete dias sozinhos não bastam.
O estudo futuro termina sem aprovação se não obtiver evidência em 45 dias.

## Pausas do ouro e unidades

No novo perfil, o contexto pode atravessar exclusivamente fechamentos previstos
no calendário congelado. A série usa candles observados em sequência de mercado,
sem preencher a pausa diária ou o fim de semana. Uma falha durante horário aberto
continua quebrando o contexto. Os 12 alvos futuros exigem M5 contíguo no relógio:
janelas que atravessam pausas são excluídas. O mesmo preparo vale na inferência.

As métricas antigas mantêm nomes técnicos terminados em `pips` por compatibilidade,
mas o cálculo e a tela usam `price_unit` do perfil: no XAUUSD, unidades de 0,01.
Comissão, slippage, valor por lote e fechamento antes da pausa vêm do perfil;
não são copiados do EURUSD.

## Onde acompanhar e restaurar

- `/treinamento?symbol=EURUSD` e `/treinamento?symbol=XAUUSD` mostram o ativo,
  estágio, recursos, checkpoint, resultados e fila compartilhada.
- PostgreSQL guarda comandos, estados, manifestos, protocolo e observações futuras.
- `data/training/datasets/<hash>/`: preços e partições congelados.
- `data/training/runs/<run_id>/`: checkpoints, pesos candidatos e relatórios.
- `data/training/releases/<run_id>/`: evidências verificáveis e configuração anterior.
- `data/training/active/<symbol>/<profile_id>.json`: modelo aprovado do perfil novo.
  O EURUSD legado conserva `data/timestral.json`.

Esses arquivos locais são ignorados pelo Git. Devem acompanhar o backup do banco
ao replicar o ambiente. O serviço Windows existente executa a fila; não é
necessário instalar uma segunda tarefa. CLI opcional:

```powershell
.venv/Scripts/python.exe run_training_lab.py --once
.venv/Scripts/python.exe run_training_lab.py --once --symbol XAUUSD
```

Os limites existentes continuam: 384 MB livres para iniciar, reserva de 128 MB,
768 MB por processo e duas horas por tentativa. Falta de recursos adia ou
interrompe o treino com motivo explícito; não reduz os limites de risco do agente.
Resultados históricos já pesquisados não são evidência independente. Implementar
o ciclo não significa que já exista um novo modelo aprovado ou lucrativo.
