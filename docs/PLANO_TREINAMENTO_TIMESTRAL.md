# Laboratório de treinamento Timestral

Evolução implantada: [aprendizado contínuo automático](APRENDIZADO_CONTINUO.md).
O piloto abaixo é o primeiro experimento arquivado; novos ciclos usam dados novos.

## Objetivo e estado

Criar e avaliar versões ajustadas do modelo de previsão, separadas do agente
demo, de seus parâmetros de entrada e do estudo prospectivo de regimes.

O Timestral-209M continua sendo o modelo ativo. A primeira prova utiliza uma
cópia do **Timestral-5M**, adequada ao computador disponível. Não é um ajuste
dos pesos do 209M e não é um modelo aprovado para operar.

| Etapa | Entrega e critério para avançar | Estado |
|---|---|---|
| 1. Ambiente | Dependências isoladas, revisões fixadas e hardware identificado | Concluída |
| 2. Prova técnica | Gradientes, alteração somente da saída, exportação e recarga fiel | Concluída em dados sintéticos |
| 3. Dataset EUR/USD | Dados congelados, qualidade, cortes cronológicos e proteção dos períodos reservados | Concluída: 74.520 candles |
| 4. Ajuste fino piloto | Treinar somente a saída do 5M; registrar configuração, custos e checkpoint | Concluído: três épocas; época 3 selecionada |
| 5. Validação de previsão | Comparar original 5M e ajustado nos mesmos cortes; 209M como controle adicional | Concluída: melhora de 0,14%, abaixo dos 2% exigidos |
| 6. Simulação e observação | Custos/risco fixos, dados novos, previsões paralelas sem ordens | Replay concluído; zero entradas. Observação futura não iniciada para candidato reprovado |
| 7. Ativação versionada | Evidência suficiente, decisão de ativação e rollback verificado | Mecanismo testado; ativação do candidato recusada corretamente |

Nenhuma etapa promove uma versão automaticamente por ter reduzido a perda de
treino ou por apresentar um trade com lucro.

Entrega integrada: **http://192.168.97.221:8097/treinamento**, mesma porta do
Aurelia FX. [Funcionamento](LABORATORIO_TIMESTRAL.md) e
[resultado do piloto real](RESULTADO_PILOTO_TIMESTRAL.md).

## Ambiente instalado

- Python 3.14, `.venv-training`, separado de `.venv` e `.venv-timestral`.
- PyTorch CPU 2.14.1, Timestral 1.0.0, NumPy, safetensors, huggingface-hub,
  psutil, psycopg/pool e ferramentas de teste.
- SDK Timestral fixado em `a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff`.
- Timestral-5M fixado em `bdd20cfc15a3fea0e4cb5ccef37f8d3ca7aa335f`.
- Especificação em `requirements-training.txt`; ambiente instalado reproduzível
  em `requirements-training-lock.txt` (CPU, plataforma Windows desta prova).

Hardware: Core i5-1345U, cerca de 16 GB de RAM e vídeo integrado Intel. O usuário
escolheu usar este computador para a prova pequena. Não foi instalado CUDA nem
contratado serviço externo. O treinamento maior exigirá medição de recursos
antes de decidir entre CPU, outra máquina ou GPU em nuvem com orçamento definido.

O [SDK desta revisão](https://github.com/mistralai/timestral/tree/a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff)
é uma implementação de inferência. O laboratório implementa treinamento próprio
sobre `model.predict_block`, preservando a normalização causal do modelo. A API
`forecaster.forecast` usa modo de inferência e não é usada para retropropagação.

## Prova executada em 22/10/2026

- Modelo pré-treinado real 5M: 5.208.960 parâmetros; 792.576 da saída ajustáveis.
- Série sintética determinística: 64 valores de contexto e 12 alvos futuros.
- Três passos AdamW, learning rate 0,00001, backbone congelado, um thread CPU.
- Perda quantílica, usando todos os quantis e escala obtida somente do contexto.
- Perda de treino: 0,48519 → 0,47771 → 0,47038.
- Gradientes finitos e pesos da saída alterados; backbone e fonte intactos.
- Exportação `config.json` + `model.safetensors`, compatível com o loader original.
- Previsões do checkpoint recarregado exatamente iguais às da cópia treinada.
- Repetições produziram o mesmo hash de pesos ajustados.
- Pico da árvore de processos: aproximadamente 366 MB; última repetição 6,57 s.
- Cinco testes isolados passaram; `pip check` não encontrou incompatibilidades.

Identificador da última prova: `c72ac8fc-1547-4229-8c79-fbc203fed658`.
SHA-256 dos pesos candidatos:
`3c09526f82ee7c107bb98d38b2fc46f17c999a4eefbf696e2f6f2dcfc4de3fdf`.
Status: **TECHNICAL_PROOF_PASSED_NOT_VALIDATED**.

Metadados desta execução persistidos no PostgreSQL, tipo
`agent_timestral_training_proof`, chave
`1e1cb37a5e1659b989303367c5ee9fb4195e9c450a2807b312506541a1d2f2ac`.
O comando de prova salva arquivos locais; este registro liga a entrega atual ao
repositório de experimentos do projeto.

Isso prova que o mecanismo funciona, não que o modelo prevê EUR/USD melhor.
A configuração e os pesos do modelo ativo não foram substituídos.

## Proteção de recursos e artefatos

O launcher usa subprocesso próprio, prioridade baixa, um thread e limite de
180 segundos. Recusa iniciar com menos de 384 MB livres e interrompe se a árvore
de processos exceder 768 MB ou a RAM livre cair abaixo de 128 MB. No Windows,
inclui o launcher do venv e seu Python descendente no monitoramento e na parada,
sem tocar nos processos do agente/ponte/MT5.

Downloads, candidatos e logs ficam em `data/training/`, fora do Git. Cada prova
tem diretório exclusivo, sem caminho de promoção para `data/models/`. O relatório
contém hashes, revisões, versões e verificações. Os pesos são arquivos; o banco
guarda metadados e resultados, não o conteúdo binário do modelo.

## Especificação da próxima etapa: dataset

1. Começar com EUR/USD M5, preço de fechamento e horizontes 3/6/12 barras, iguais
   aos usados no projeto. Não acrescentar covariáveis na primeira comparação.
2. Usar candles do MT5 no PostgreSQL, com UTC validado, corte de conhecimento,
   hash e origem congelados. Não usar somente as raras operações realizadas:
   previsão precisa de janelas de preços, inclusive quando não houve trade.
3. Separar treino/validação/teste por tempo; excluir alvos que atravessem as
   fronteiras. Estatísticas de transformação usam só contexto/treino permitido.
4. Registrar sobreposição de janelas e avaliar incerteza por blocos temporais;
   milhares de janelas vizinhas não equivalem a milhares de eventos independentes.
5. Preservar o período reservado ao estudo prospectivo atual. Não utilizá-lo no
   treino para depois apresentá-lo como prova independente de melhora.
6. Dados históricos já examinados servem como teste retrospectivo identificado;
   a conclusão final requer período novo registrado antes de consultar resultados.
7. Avaliar pinball loss, MAE em pips, direção e cobertura dos intervalos por
   horizonte/sessão, comparando também com previsão de preço constante.

As referências de trading continuam orientando as regras externas e a avaliação
das operações; os PDFs não são diretamente alimentados como preços no Timestral.

Não falta informação do usuário para preparar o dataset inicial. Uma pergunta
sobre GPU/orçamento só será necessária se a medição do piloto indicar necessidade.

## Reprodução da prova

Na raiz do projeto:

```powershell
python -m venv .venv-training
.venv-training/Scripts/python.exe -m pip install -r requirements-training.txt
.venv-training/Scripts/python.exe run_training_proof.py --prepare
.venv-training/Scripts/python.exe run_training_proof.py
```

Para reproduzir as versões instaladas, usar `requirements-training-lock.txt`.
Os ambientes operacionais e os serviços da VM não precisam ser reinstalados.
