# Contexto das entradas da candidata H1

## Pergunta

Quais características já conhecidas na entrada diferenciam os resultados da
candidata de rompimento com reteste em H1?

Esta é uma investigação descritiva posterior aos resultados, não uma nova
estratégia validada. Não foram enviados pedidos à corretora, alterados pesos do
Timestral ou aplicados novos filtros ao agente ou ao observador prospectivo.

## Fonte e método

Foi reutilizada a [validação ampliada](VALIDACAO_H1_AMPLIADA.md), relatório
`50f2555e7fd9bef884744624196004bb0517992cdef16ad9d1853064a09288ff`.

Cada operação encerrada foi vinculada ao seu sinal congelado, reconciliando a
quantidade e o resultado financeiro sem descartar perdas. A análise principal
abrange as **186 operações das quatro carteiras anuais completas de 2021–2024**.
O resultado parcial de 2025 e o período de seleção de 2026 aparecem separados.

Comparações definidas no protocolo: compra/venda, alinhamento H1, alinhamento
D1, sessão de Londres/Nova York/sobreposição e motivo da saída. Não houve
busca por limites numéricos nem combinação de filtros. O motivo da saída é
uma informação posterior, útil para diagnóstico; não pode ser usado como
característica conhecida na entrada.

Foi feita uma segunda versão da auditoria para distinguir disponibilidade de
histórico e neutralidade: o cálculo de tendência retorna zero com menos de 60
candles, mas zero também pode ocorrer com dados suficientes. O agrupamento
inicial é preservado; a segunda versão reproduz a agregação congelada no
instante de cada sinal e separa `insufficient_history` de `neutral`.

Os timeframes desta pesquisa são agregados a partir de M5 com o calendário
existente. Eles não são uma captura independente dos candles D1 nativos do MT5.
Lacunas inesperadas reiniciam a agregação; aquecimento de 30 dias também pode
ser insuficiente para obter 60 candles diários. Esses mecanismos não foram
alterados para melhorar os resultados.

## Comparações principais: 2021–2024

| Contexto | Encerradas | Resultado líquido (US$) |
|---|---:|---:|
| Compra | 80 | +7,60 |
| Venda | 106 | −4,38 |
| H1 alinhado | 180 | +11,51 |
| H1 com valor zero | 6 | −8,29 |
| Somente Londres | 60 | +26,32 |
| Somente Nova York | 54 | −19,90 |
| Sobreposição Londres/Nova York | 72 | −3,20 |

São subconjuntos das operações já executadas pela simulação original.
**Não representam carteiras novas com filtros aplicados.** Se uma entrada for
removida, outras podem passar a ser executadas devido a posição livre e limites
de risco; por isso não se pode obter um novo backtest apenas somando esses grupos.

### A direção isolada não resolve

As compras ganharam no agregado, mas perderam US$ 15,36 em 2021 e US$ 7,79 em
2024. As vendas também alternaram resultados. Operar somente um lado não tem
suporte estável nesta comparação.

O grupo H1 alinhado teve fator de lucro de apenas 1,07 e perdeu US$ 17,78 em
2024, mesmo com 50 operações. Assim, acrescentar apenas confirmação H1 não
explica nem elimina o ano negativo.

### Sessão importa, mas a soma esconde diferenças

| Ano | Somente Londres (US$) | Somente Nova York (US$) | Sobreposição (US$) |
|---|---:|---:|---:|
| 2021 | −15,17 | −1,50 | +5,59 |
| 2022 | +36,00 | −6,07 | −8,68 |
| 2023 | +6,36 | −8,12 | +13,79 |
| 2024 | −0,87 | −4,21 | −13,90 |

O resultado da sessão exclusiva de Nova York foi negativo em todos esses anos.
Isso justifica investigar horário e tempo restante de sessão como hipóteses
separadas. Londres, porém, concentra o ganho em 2022 e também tem anos negativos;
o grupo não está validado como estratégia.

### Custos e saídas

O bruto das 186 operações foi US$ 43,77, com US$ 40,55 de custos modelados e
líquido de apenas US$ 3,22. Aproximadamente 93% do bruto foi consumido por custos.

- 117 saíram pelo fim de sessão, somando +US$ 91,15.
- 60 atingiram stop, somando −US$ 123,17.
- Uma teve stop com salto de preço: −US$ 1,43.
- Oito atingiram o alvo: +US$ 36,67.

Isso não autoriza remover stops nem manter posições após a sessão: o resultado
desses cenários exige outra simulação, incluindo exposição, custos e dados que
não estão cobertos pelo modelo atual. O encerramento por sessão foi negativo em
2024, portanto ele também não produz vantagem em qualquer contexto.

## Disponibilidade de D1

| Estado D1 reconstruído em 2021–2024 | Encerradas | Líquido (US$) |
|---|---:|---:|
| Histórico insuficiente: menos de 60 candles | 117 | −34,47 |
| Dados suficientes, tendência neutra | 21 | −1,93 |
| Alinhado à operação | 41 | +37,00 |
| Contrário à operação | 7 | +2,62 |

Dos 138 registros inicialmente agrupados por valor zero, 117 eram falta de
histórico e apenas 21 eram neutralidade com dados suficientes. Em 2021, todas
as 30 operações encerradas estavam sem contexto D1 suficiente. Isso não
significa que a API inteira do MT5 não tenha histórico diário; significa que
o agregador desta pesquisa não o tinha disponível naquele instante.

O alinhamento D1 teve resultado positivo no agregado, mas o mesmo grupo perdeu
US$ 2,19 em 2024, com 13 operações. Nas 12 operações encerradas antes do bloqueio
de 2025, perdeu US$ 13,26; esse último é um parcial, não resultado anual.
Em 2026, o grupo sem histórico D1 suficiente somou +US$ 24,84 dos encerramentos,
enquanto D1 alinhado somou apenas +US$ 0,88. Assim, disponibilidade e alinhamento
diário não explicam o lucro de maneira estável entre períodos.

O estudo não transformou essa descoberta em veto D1 nem em mudança do
agregador ativo. Primeiro é necessário testar uma definição de contexto diário
com disponibilidade explícita e fontes comparáveis. Uma captura nativa D1 seria
outra construção de candles; precisa respeitar o fechamento da corretora e ser
comparada como nova hipótese, sem substituir silenciosamente o diário UTC
agregado empregado nestes resultados.

## Uso no projeto

Continuação: [carteiras completas por horário e família H1](TESTE_DE_HORARIOS_H1.md).
Os resultados posteriores não aprovaram os novos filtros de horário.

Esta entrega fornece diagnósticos e hipóteses de pesquisa, não uma permissão
de operar. O observador H1 continua coletando preços novos com a regra congelada.
As próximas comparações deverão ter regras e critérios registrados antes de
medir seus resultados, com avaliação adicional em dados futuros.

Prioridades fundamentadas por este diagnóstico:

1. Registrar disponibilidade e neutralidade como estados distintos em novas
   hipóteses de contexto, preservando as reproduções existentes.
2. Testar isoladamente uma regra de horário/tempo restante de sessão. O padrão
   negativo de Nova York é descritivo e ainda exige uma carteira nova completa.
3. Comparar o contexto diário com dados suficientes, sem combinar filtros para
   selecionar apenas os negócios que já sabemos terem dado lucro.

Nenhum desses itens constitui aprovação de uma alternativa para execução.

Relatório final `agent_h1_context_review`:
`d44baa83fd08a408e60cd8ef9cfa03262dbe86cd03e3fc058215d690e42810a6`.
Protocolo da auditoria de disponibilidade:
`31e5c601ea2970ec0044bfcd04b248365c2c3357f42544feb1c05e36e09e997b`.
Relatório inicial, anterior à separação de disponibilidade, preservado:
`a51ca50a8b23770497255b8345bf6e8656aabca0ebb87de6e21c74de401f1bf0`.

76 testes direcionados aprovados, incluindo a distinção entre histórico
insuficiente e neutralidade, reconciliação dos grupos e rejeição de contexto futuro.

Reprodução:

```powershell
.venv/Scripts/python.exe run_h1_context_review.py
```

Protocolos e relatórios ficam no PostgreSQL em `agent_h1_context_protocol` e
`agent_h1_context_review`. Os JSONs completos estão em `data/reports/`, fora do Git.
