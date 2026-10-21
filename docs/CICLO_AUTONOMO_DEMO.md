# Ciclo autônomo na conta demo

## Fluxo de uso

1. Abrir o MT5, conectar à conta **demo** e habilitar AlgoTrading.
2. No painel Aurelia FX, escolher o lote e o ambiente **MT5 Demo**.
3. Clicar em **Iniciar agente**. Não há credencial do projeto nem aprovação por operação.

O agente prepara os últimos 30 dias do ativo, aproveita o histórico local e constrói
o contexto de regime, estrutura, tendência, sessões e price action. Quando existe
um gatilho técnico, avalia o Timestral e seleciona uma hipótese elegível para aquele
contexto. Os conceitos dos materiais estão expressos em regras e características
do projeto; os PDFs não são pesos treinados diretamente no Timestral.

## O que aprende automaticamente

O catálogo inicial contém pullback com direção H1, pullback confirmado pelo
Timestral e gatilho de price action. A seleção combina evidências históricas de
desenvolvimento com resultados novos por contexto. Após um resultado não positivo,
prioriza outra hipótese elegível quando há alternativa. Não inventa código de uma
estratégia nova a cada perda e não altera os pesos do Timestral automaticamente.

Ganhos e perdas são evidências, não comprovação de uma estratégia. A memória é
persistida no PostgreSQL. Validação e teste final históricos permanecem fora da
memória inicial de seleção. Os experimentos demo não recebem o rótulo de modelo
validado nem habilitam operações em conta real.

## Execução e recuperação

- Cada conexão e envio verifica a identidade da conta e exige o tipo DEMO.
- Toda entrada inclui stop e alvo nativos, lote fixo e verificação de custos,
  margem, spread e limites de risco existentes.
- Uma intenção durável é confirmada no PostgreSQL antes de chamar o MT5.
  Timeout ou resposta ambígua bloqueiam reenvio até reconciliação.
- Ordem, negócio e posição são identificadores distintos. A confirmação usa
  a relação entre negócios e posição, além da identificação própria do projeto.
- O resultado inclui lucro, comissão, swap e taxas informados pelo MT5.
  Cada resultado atualiza a memória uma única vez, na mesma transação do checkpoint.
- Pausar suspende novas entradas. Posições existentes continuam protegidas e
  acompanhadas. Parar solicita o encerramento das posições identificadas do projeto.
- Conta, terminal ou relógio diferentes não herdam autorização anterior.

O simulador local continua disponível como ambiente separado, com preenchimentos
estimados. Seus saldos e resultados não se confundem com os da conta demo.

## Pré-requisitos

MT5 e o serviço Windows precisam estar ativos. A VM mantém o painel e PostgreSQL;
ela não substitui o terminal. AlgoTrading desligado impede envios: o painel informa
essa condição e a verificação é repetida automaticamente.
