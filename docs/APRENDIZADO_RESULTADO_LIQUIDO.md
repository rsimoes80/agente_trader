# Aprender o resultado líquido de uma hipótese

## O que foi testado

Uma previsão de preço não responde diretamente se uma operação, com stop,
alvo, prazo e custos, será vantajosa. Foi criado um modelo pequeno de pesquisa
que aprende o resultado líquido em R usando as características já existentes:
tendência, sessão, geometria de preço, volatilidade, spread e previsões Timestral.
Ele não altera os pesos do Timestral e não tem acesso a ordens.

O ajuste é uma regressão regularizada, com penalidade fixa 10, características
padronizadas e limiar fixo de entrada acima de zero R previsto. Não foi feita
busca de penalidades, limiares ou melhores subconjuntos após os resultados.
As características extremas são limitadas na padronização; **os resultados
financeiros não são truncados**. Uma perda de 6R deve continuar sendo 6R.

## Treino e teste sem usar o futuro

Os 1.421 candidatos do catálogo foram simulados novamente com os custos atuais,
prazo máximo de 12 candles M5 e encerramento antes do fechamento conhecido da
sessão/corretora. Um candidato fora da janela de execução foi excluído; 1.420
resultados ficaram disponíveis. Os rótulos antigos não foram usados como entrada.
Esses rótulos são hipóteses isoladas sobrepostas, não operações independentes.

No início de março, maio, julho e setembro/2026, o modelo foi ajustado somente
com resultados já encerrados antes daquela data. Depois ficou congelado durante
o período seguinte. Carteiras base e filtrada foram simuladas integralmente com
as mesmas regras de risco e custos. A estratégia inicial é de pesquisa em todos
os regimes; ela não remove o veto de tendência do executor demo.

| Período avaliado | Exemplos anteriores para ajuste | Carteira base USD | Carteira com modelo USD | Encerradas com modelo |
|---|---:|---:|---:|---:|
| Março–abril | 325 | −57,30 | −28,92 | 63 |
| Maio–junho | 827 | −26,71 | +0,15 | 5 |
| Julho–agosto | 1.073 | −27,62 | −1,39 | 2 |
| Setembro–20 de outubro | 1.240 | −21,77 | −1,12 | 2 |

O pequeno ganho de maio–junho teve somente cinco operações. Nos três primeiros
períodos, o erro de previsão em R foi pior que simplesmente prever a média dos
resultados de treino; no último, a melhora foi pequena e as entradas escassas.
O modelo **não foi aprovado**. Entrar menos e perder menos no total não comprova
seleção de operações lucrativas. Não houve redução dos mínimos de amostra.

Os dados já foram pesquisados. Essa avaliação walk-forward não transforma o
catálogo em uma amostra prospectiva independente.

## Reprodução e persistência

- Executar `python run_reward_model_experiment.py`.
- Protocolo: `00d3ebf11b1a93360ae6a8c94b00b294c730b43c88eb410673c0b4015614e8c3`.
- Relatório PostgreSQL `agent_reward_experiment`:
  `1d4962cddc75c0d6a86a286710b2a9afb8c16c8e04922db688c5bddce68ceb06`.
- Modelos por período, rótulos e suas linhagens ficam em registros separados,
  com hashes, no PostgreSQL. A configuração e os pesos operacionais foram preservados.
- Sete testes cobrem aprendizado sintético, serialização, dados futuros,
  valores inválidos, perdas grandes, fechamento conhecido e exposição censurada.

## Consequência para o projeto

O mecanismo consegue ajustar pesos a partir de erros e acertos e avaliar a
seleção posteriormente. Neste catálogo ele não demonstrou capacidade suficiente
de generalização ou vantagem econômica para virar política operacional.
Não será ativado automaticamente por estar tecnicamente funcionando.
