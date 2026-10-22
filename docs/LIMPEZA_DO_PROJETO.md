# Limpeza do projeto - 22/10/2026

## Criterio

Manter operacao demo, captura MT5, graficos, memoria PostgreSQL, aprendizado
continuo, treinamento Timestral e ferramentas usadas para validar hipoteses.
Verificar imports, comandos executaveis, referencias textuais e chamadas de
modulos por subprocesso antes de considerar um componente sem uso.

## Excluido

- Clone local `nautilus_trader/`: 5.302 arquivos, 165.088.706 bytes logicos
  (157,4 MiB). Git limpo, sem alteracoes ou arquivos novos. Nenhum import ou
  comando operacional do Agente Trader - IA depende desse clone.
- Nove documentos de funcionalidades retiradas ou planos substituidos:
  `DUKASCOPY_FIX.md`, `INTEGRATION_NAUTILUS.md`, `DECISAO_E_APRENDIZADO.md`,
  `docs/human_review_panel.md`, `docs/conversation_gap_audit.md`,
  `docs/diagnostic_initial_audit.md`, `docs/agent_live_simulation.md`,
  `docs/IMPLEMENTACAO_OPERACIONAL_STATUS.md` e
  `docs/PLANO_OPERACIONAL_E_TREINAMENTO.md`.

Os nove documentos somavam 64.858 bytes e 920 linhas. Permanecem recuperaveis
no historico Git. O clone externo pode ser obtido novamente do repositorio
publico original; nao e dependencia do produto.

## Corrigido

- `architecture.md` descreve os processos e arquivos existentes, em lugar do
  antigo `app.py`, FIX e plano de migracao nao vigente.
- O cabecalho do Prompt Mestre V4 aponta para o ciclo demo e aprendizado
  continuo atuais. Foram retiradas instrucoes de aprovacao manual e simulacao
  que ja nao representam a operacao.
- O README aponta para a arquitetura e este registro de limpeza.

## Mantido e motivo

- Replay, simulador, validacao temporal, estudos H1/regime: avaliacao de
  hipoteses, comparacao com custos e preservacao da pesquisa prospectiva.
- `training/study_engine.py`: chamado dinamicamente por subprocesso.
- `mt5_clock.py`: importado pelo provedor MT5, inclusive pelo namespace `src`.
- `knowledge.py` e catalogo: contrato de leitura/validacao das referencias.
  Nao e treinamento automatico de PDFs nem esta ligado diretamente ao envio
  de ordens. Mantido como biblioteca de validacao do conhecimento do projeto.
- Prova tecnica e comandos de coleta: reproducao e diagnostico do ambiente
  isolado, separados do ciclo automatico.
- Testes existentes e dependencias opcionais de pesquisa/treinamento:
  verificacoes e ambientes distintos do processo operacional.

## Dados e operacao

Nenhuma exclusao no PostgreSQL, modelos, experiencias, PDFs, historicos,
backups ou configuracoes privadas. Os 918 MB medidos no banco e os dados da VM
nao foram classificados como lixo pelo tamanho. Registros antigos preservam
proveniencia; uma politica de retencao exige analisar cada tipo separadamente.

Esta limpeza nao muda estrategia, lote, risco, pesos nem processos ativos.
Nao exige reiniciar o agente, o MT5 ou a API. Testes automatizados nao foram
executados nesta limpeza documental; a verificacao foi por inspecao de
referencias e diff.
