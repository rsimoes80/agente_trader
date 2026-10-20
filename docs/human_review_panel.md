# Painel de revisão humana

Acesso: `/diagnostico`, na área **Amostras para revisão**. A implementação
reaproveita o gráfico, os filtros e os registros imutáveis do diagnóstico V4.

## Fluxo

1. Selecione uma observação. O gráfico termina no candle usado na decisão;
   não busca candles posteriores. Os limites da faixa continuam destacados.
2. Leia o resumo: ativo/período, regime, decisão, hipótese e critérios
   efetivamente registrados antes da decisão. Quando não houver hipótese ou
   contrato, essa ausência aparece explicitamente. O painel não cria previsões.
3. Informe seu nome e escolha **Concordo**, **Discordo** ou **Não sei avaliar**.
   Discordar exige escolher regime, tendência, níveis, confirmação, dados ou
   outro motivo. Texto e classificação alternativa de regime são opcionais.
4. Salve a avaliação. Só então o botão de comportamento posterior é liberado.
5. Consulte os próximos **12 candles fechados** (60 minutos no M5). A janela é
   fixa, não escolhida em função do resultado. São exibidos fechamento,
   variação absoluta de preço, máxima e mínima. Dados incompletos, ainda não
   fechados ou conflitantes impedem uma comparação completa.
6. Use **Próxima observação** para continuar. Ao voltar, informar o mesmo nome
   recupera a referência da avaliação entre as revisões recentes da observação.

O nome continua sendo um rótulo informado, sem autenticação individual.
Revisões de outras pessoas ficam ocultas na interface até existir uma resposta
do revisor informado. Isso não constitui revisão cega ou uma fronteira de
segurança: a classificação do agente está visível, o usuário pode conhecer o
mercado e a API de diagnóstico permanece acessível na rede privada existente.

## Hipótese e resultado

Hipóteses e contratos são lidos dos eventos existentes, vinculados pelo ID da
hipótese, somente quando já estavam registrados no instante da decisão.
As avaliações posteriores são as do motor de expectativas existente, dentro
da janela consultada; o painel não infere confirmação a partir de preço alto
ou baixo nem reinterpreta critérios em texto livre.

O observador atual pode registrar NO_TRADE sem hipótese operacional. Nesse
caso é possível revisar regime/evidências e acompanhar o preço depois, mas
**não declarar uma hipótese confirmada ou invalidada**. Horários legados sem
contrato UTC validado não liberam a comparação posterior.

Dados posteriores usam o mesmo ativo, período e dataset do replay ou fonte e
clock_id do observador. Apenas candles fechados entram no resultado.
Em replay, a janela também fica limitada às decisões da mesma execução e
partição: não revela candles da validação ou do holdout seguinte.

Lacunas na janela, inclusive interrupções de coleta ou de negociação, são informadas;
não se preenchem candles artificialmente. Novas consultas são explícitas pelo
botão; enquanto aguarda dados, clique novamente mais tarde.

## Persistência e aprendizado

- `human_regime_review`: preservado e estendido com parecer, motivo,
  classificação opcional, referência de sessão e leitura original congelada.
- `human_review_outcome`: registra a consulta posterior, revisão de origem,
  janela, cobertura, medidas descritivas e eventos do motor quando disponíveis.
- Ambos usam `project_records` append-only no PostgreSQL existente. Nenhuma
  tabela nova ou migração é necessária. Repetir uma avaliação cria um novo
  registro; não sobrescreve a primeira opinião.
- Nova avaliação informa se já havia consulta de resultado para o mesmo nome
  e decisão. Isso sinaliza exposição prévia sem afirmar independência estatística.
- Classificação de regime omitida não entra na matriz de concordância de
  rótulos. Concordar com a leitura geral não inventa uma classificação humana.

Os registros permitem estudar discordâncias e formular hipóteses offline.
Não são rótulos automáticos de lucro, não alimentam treino diretamente, não
alteram a estratégia nem autorizam operações. Validação, holdout e aprovação
de versões continuam necessários.

## Endpoints

- `POST /api/diagnostics/reviews`: endpoint existente, agora aceita `verdict`
  (`agree`, `disagree`, `unsure`), `reason_category` e `label` opcional para
  revisões estruturadas. Chamadas legadas com rótulo continuam compatíveis.
- `POST /api/diagnostics/review-outcomes`: exige `review_id` de uma revisão
  estruturada salva. Registra a consulta e devolve a comparação disponível.
- Os dois endpoints mantêm validação CSRF/Origin do diagnóstico. O token de
  sessão de observação não é exigido para anotar uma revisão.

Nesta entrega foram feitas análise estática Python e verificação de sintaxe
JavaScript. Não foram adicionados ou executados testes automatizados.
