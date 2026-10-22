# Laboratório Timestral no Aurelia FX

## Acesso e funcionamento

**http://192.168.97.221:8097/treinamento** — mesma aplicação e mesma porta.
O painel principal contém o link **Treinamento**.

A página mostra o progresso real registrado no PostgreSQL. O botão **Executar
prova** solicita um trabalho ao Windows; **Cancelar treino** cancela somente
esse trabalho. A tarefa `AgenteTrader-TrainingLab` verifica a fila a cada minuto
e ao entrar no Windows. Não é preciso manter a página aberta. Este computador
precisa estar ligado e conectado à VM para executar o treino. Os preços já
congelados no banco dispensam o MT5 durante a prova histórica; a operação e a
coleta ao vivo continuam dependendo do terminal e da ponte.

Não há outra porta pública, credencial nova, aprovação por operação ou processo
de treino na VM Linux. PyTorch e o modelo pequeno ficam no Windows escolhido.

## Entregas do piloto

1. **Histórico:** exportação de todos os candles M5 do maior arquivo congelado
   compatível, não apenas de oportunidades que viraram trades. Confere hashes,
   fonte, corte de conhecimento e partições recalculadas. O período reservado ao
   estudo de regimes iniciado em 22/10 fica fora do treino.
2. **Ajuste:** Timestral-5M original fixado por revisão, backbone congelado,
   somente a saída treinável. Três épocas, AdamW, semente 31, contexto 256 e
   12 passos futuros. O treino recebe preços; os livros orientam as regras
   externas de tendência, gatilho e risco.
3. **Comparação:** validação escolhe a época pelo pinball da saída nativa. O
   candidato é congelado antes do teste. Os resultados finais usam o mesmo
   `TimestralForecaster.forecast` público da operação, inclusive simetrização.
   Original 5M, candidato 5M e preço constante usam os mesmos alvos. O 209M
   arquivado é apenas controle secundário em entradas exatamente iguais.
4. **Simulação:** replay causal completo do período de teste, com 60 dias
   anteriores de aquecimento, pullback confirmado pelo Timestral, regras H4/H1
   e custos existentes. Compara carteiras com uma posição por vez, não soma
   trades hipotéticos sobrepostos. Não reproduz a escolha adaptativa de todas
   as hipóteses do robô. Não envia ordens.
5. **Decisão:** candidato reprovado permanece arquivado. O modelo ativo não
   muda. Caso passe retrospectivamente, ainda exige estudo prospectivo próprio,
   registrado antes da coleta; não reutilizar o estudo de regimes como se fosse
   validação deste candidato.

## Critérios definidos antes do treino

Protocolo: `src/aurelia_fx/training/protocol.py`, persistido no PostgreSQL.

- Pelo menos 200 janelas de avaliação, melhora mínima de 2% no pinball e limite
  inferior positivo no intervalo de 95%, reamostrando dias inteiros.
- MAE não piora mais que 2%, direção não perde mais que 3 pontos percentuais e
  cobertura Q10–Q90 entre 70% e 90%, em cada horizonte.
- Pelo menos 20 operações encerradas por versão, lucro líquido positivo, não
  inferior ao original, drawdown sem piora e nenhuma exposição sem resolução.
- Promoção requer também pelo menos sete dias de dados futuros independentes e
  20 operações por versão. O calendário sozinho não produz aprovação.

O arquivo histórico já foi examinado em pesquisas anteriores. A separação por
tempo evita vazamento entre os alvos deste treino, mas não transforma dados
conhecidos em evidência prospectiva nova. Repetir a prova é reprodução técnica,
não uma nova amostra independente. Não ajustar parâmetros usando o teste final
e continuar chamando esse mesmo período de teste independente.

## Recursos, registros e recuperação

O launcher operacional não importa PyTorch. Adquire uma trava PostgreSQL e
inicia somente seu subprocesso `.venv-training`. Prioridade baixa, um thread,
início com 384 MB livres, teto de 768 MB para toda a árvore e parada abaixo de
128 MB livres. Limite do trabalho: duas horas. Esses limites são do laboratório,
não um timeout de sessão do agente. Não fecha MT5 ou aplicativos do usuário.

Execução, estado e cancelamento são identificados por `run_id`; comandos são
idempotentes. Cancelar ou iniciar outra execução impede publicações da anterior.
Uma tarefa sobreposta não treina novamente. Erro técnico requer revisão e
retomada explícita por `--retry`. Um candidato já congelado sem relatório
completo não é retreinado silenciosamente depois de possível acesso ao teste.

`data/training/datasets/<id>` contém arrays e manifesto. `data/training/runs/<id>`
contém logs, relatórios, pesos selecionados e checkpoint compatível com o SDK.
Arquivos binários ficam fora do Git; metadados e relatórios ficam em
`agent_timestral_training_dataset`, `agent_training_lab_protocol`,
`agent_training_lab_state` e `agent_training_lab_command` no PostgreSQL.

O mecanismo de versão/rollback é explícito:

```powershell
.venv/Scripts/python.exe run_training_release.py activate <run_id>
.venv/Scripts/python.exe run_training_release.py rollback <run_id>
```

Ativação recusa candidato sem todos os relatórios aprovados, evidência futura
compatível e hashes íntegros. Salva a configuração anterior antes de trocar a
referência. A inferência reconfere os arquivos do release. Esses comandos não
reiniciam o agente nem enviam ordens; a troca só entra na próxima inicialização
do subprocesso de inferência. Os testes de ativação/rollback usam configurações
temporárias, sem alterar o modelo em operação.

Para instalar a tarefa isolada: `install_training_startup.ps1`. Para consumir
uma solicitação manualmente: `.venv/Scripts/python.exe run_training_lab.py --once`.
Dependências: `requirements-training.txt`; reprodução exata:
`requirements-training-lock.txt`.
