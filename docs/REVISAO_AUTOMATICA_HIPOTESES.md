# Crítica e revisão automática de hipóteses

Implementação própria, inspirada na separação entre hipótese, crítica e reflexão
do TradingAgents. Não instala o framework, não usa um LLM e não altera os pesos
do Timestral. As críticas são regras explícitas, não interpretações dos livros.

## Ciclo integrado

1. Antes de enviar uma oportunidade ao simulador paralelo existente, registrar
   evidências, contradições, corpo/ATR, confirmação dos dois horizontes do
   Timestral, expectativa e stop. Dado ausente não significa discordância.
   A versão V3 também compara o deslocamento mediano previsto para 30 minutos
   com spread observado nas características do sinal, slippage 0,2 pip por lado
   e comissão de pesquisa USD35/milhão/lado. É um filtro econômico experimental,
   não uma estimativa calibrada de lucro esperado nem tarifa confirmada da conta.
2. Ao encerrar uma simulação base, registrar ganho bruto, custos, ganho líquido,
   excursão favorável, conformidade reportada pelo simulador e crítica original.
   Não atribuir causalidade ao motivo da perda: a classificação é descritiva.
3. Após 20 resultados no mesmo contexto, procurar uma crítica com pelo menos
   oito ocorrências e soma líquida negativa. Congelar uma proposta: excluir
   oportunidades que apresentem essa crítica. A escolha usa apenas descoberta.
4. Observar por 14 dias os sinais futuros do mesmo contexto. Resultados de
   sinais anteriores à proposta nunca entram na avaliação futura. Aguardar
   mais um dia para resolver exposições; exigir pelo menos 30 encerramentos.
5. Comparar resultado original e resultado que exclui as oportunidades marcadas.
   Executar também duas carteiras independentes: base e filtro, com custos,
   limites e disponibilidade de posição próprios. Uma entrada evitada pode
   liberar outra oportunidade; remover trades de uma lista não reproduz isso.
   Exigir resultado filtrado positivo e limite inferior descritivo positivo
   da diferença pareada. Dependência entre trades impede interpretar esse
   limite como comprovação estatística. O prazo não é prolongado para obter
   resultado favorável; amostra insuficiente é uma conclusão possível.

Só há uma proposta ativa por checkpoint de pesquisa. Cada combinação de contexto
e crítica só pode ser testada uma vez por versão. Após conclusão, outra proposta
exige novas observações com sinais posteriores à avaliação encerrada. O histórico
das últimas 30 propostas fica no checkpoint. Não se repete a mesma regra até ganhar.
As variantes paralelas não são contadas como observações independentes: somente
a base alimenta este ciclo. Uma lacuna que censure exposição invalida a coleta
futura e elimina os registros de descoberta dessa janela.

## Persistência e visualização

O estado fica em `continual.hypothesis_review`, dentro do checkpoint transacional
de aprendizado já armazenado no PostgreSQL por `learning_storage`. Reinícios
preservam descoberta, proposta e resultados futuros. Mudança de lote reinicia
o experimento, conforme o ciclo existente. A lista descritiva conserva os últimos
1.000 resultados; a proposta mantém sua própria amostra futura separada.

O resumo aparece no painel existente, na seção de aprendizado, sem novo controle
manual. Não requer credencial ou intervenção para cada hipótese.

## Limites e próxima validação

A ablação de oportunidades é somente uma etapa diagnóstica. Mesmo se ela for
favorável, as duas carteiras precisam ter amostra mínima e resultado líquido
favorável da filtrada. O status `PROMISING_REQUIRES_INDEPENDENT_CONFIRMATION`
exige outra avaliação independente antes de qualquer promoção. Uma amostra curta
ou carteira desfavorável não autoriza ativação.
Não altera a seleção existente, os limites de risco ou as ordens demo. O mecanismo
preexistente de promoção de outras variantes permanece separado desta pesquisa.
Resultados da conta demo não são misturados com as simulações deste experimento.

Arquivos: `hypothesis_review.py`, integração em `continual_learning.py` e resumo
em `static/operation.js`. Não foram adicionadas dependências.

## Validação reproduzível

`python run_hypothesis_review_experiment.py --long-comparison` lê o dataset
congelado `661f1b42-0b1d-4066-a145-85f8cd0334ae`, verifica hashes dos registros
e da série MT5, registra o protocolo e grava os resultados no PostgreSQL e
em `data/reports/hypothesis-review-*.json`. Não chama o broker nem treina pesos.
Os dados já foram pesquisados: separar cronologicamente não os transforma em
evidência prospectiva inédita.

O teste longo compara os quatro filtros individualmente com a base, usando
descoberta anterior a julho/2026 e checagem de julho a outubro/2026, com replay
completo, custos, encerramento de sessão conhecido e mesma purga de uma hora.
Só pode ser selecionado filtro positivo com pelo menos 50 operações e PF 1,1
na descoberta. Perdas menores continuam sendo perdas: não há vencedor negativo.
O universo ampliado é pesquisa; não altera a política de entradas em produção.
