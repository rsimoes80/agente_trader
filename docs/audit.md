# Auditoria inicial do Aurelia FX

**Escopo:** código próprio na raiz, `static/`, `deploy/`, arquivos de dados por metadados e inventário de `Aprendizado/`, `avulso/` e `nautilus_trader/`. A árvore contém cerca de 5.300 arquivos de NautilusTrader e 160 arquivos legados/artefatos em `avulso/`; esses diretórios foram classificados como código de terceiros e material de referência, não auditados linha a linha como código próprio.

## Arquitetura encontrada

- `app.py` é o servidor HTTP local, com rotas de configuração, feed, análise, backtest, otimização, credenciais e arquivos estáticos.
- `static/` contém a interface HTML/CSS/JavaScript sem framework.
- `analysis.py` implementa indicadores TA-Lib, pivôs confirmados, filtros de confluência e preço/stop/alvo hipotéticos.
- `backtest.py` percorre candles, simula entrada na barra seguinte, custos aproximados, limites diários e drawdown.
- `strategy_optimizer.py` compara perfis em janelas cronológicas e reserva uma janela final de avaliação.
- `learning.py` treina uma regressão logística pequena, validada cronologicamente, a partir de resultados de simulação.
- `mt5_provider.py` lê dados do terminal local Windows; `mt5_bridge.py` oferece uma ponte HTTP autenticada somente para leitura até a página publicada na VM Linux.
- `dukascopy_feed.py` abre uma sessão FIX de leitura e agrega ticks em candles em memória; `typesafe_jev.py` envia uma revisão externa opcional de candidatos.
- `security.py` protege credenciais locais com DPAPI do usuário Windows.
- `data/` contém configuração, histórico de aprendizado, busca de estratégias, logs e segredos de execução. Os arquivos variáveis não devem ser tratados como código-fonte nem copiados para relatórios.
- `Aprendizado/` contém cinco PDFs (Pullback, SMC, Wyckoff 2.0 e duas edições de Trading in the Zone). `RESEARCH_NOTES.md` resume apenas Pullback, SMC e Wyckoff.
- `avulso/` contém versões legadas de robôs, instaladores binários e dados de exemplo. Não deve ser importado automaticamente para o caminho ativo.
- `nautilus_trader/` é uma árvore grande de terceiros; a integração atual está documentada, mas o app não usa o motor para enviar ordens.

## Reutilizar

- `analysis.analyze`: fonte para features/sinais explicáveis durante a migração, após separar cálculo de decisão e validar entradas.
- `backtest.run_backtest`: referência de execução simulada; não substitui um RiskManager de domínio.
- `mt5_provider`: adaptador de dados MT5 de leitura, a encapsular atrás de uma interface.
- `dukascopy_feed`: adaptador de cotações/candles em tempo real, com limitações de volume OTC e credenciais FIX.
- `learning`: baseline de pesquisa; deve receber apenas resultados identificados por experimento e fora de amostra.
- `security`: proteção local Windows; não é solução de secrets para serviço Linux.
- interface de gráficos como apresentação; não deve ser fonte de decisão ou persistência.

## Riscos e lacunas

1. Não há `.git` na raiz acessível, portanto não há histórico/rollback verificável para esta cópia.
2. Não foi encontrado conjunto de testes próprio na raiz. `pytest` citado/arquivos de teste dentro da árvore Nautilus pertencem ao terceiro.
3. `sanitize_config` mantém modo `paper`; não há integração de envio de ordens no caminho ativo. Isso é um bloqueio positivo, mas não há ainda uma política de risco central que qualquer executor tenha de consultar.
4. O backtest usa unidades abstratas, supõe moeda de conta igual à moeda cotada e aproxima spread/slippage. Não valida tick value, tamanho de lote, conversão cambial, comissões, swap, liquidez ou fills reais.
5. Feed FIX guarda somente candles recentes em memória; não há histórico durável/replay reproduzível e a reconexão/recuperação precisa ser demonstrada.
6. Histórico de aprendizado e resultados de busca são JSON locais; há escrita atômica em algumas rotas, mas não há repositório transacional, migração de schema ou isolamento concorrente uniforme.
7. A aprendizagem CSV pode reutilizar operações de backtests com janelas sobrepostas. Deduplicação por candle reduz contagem duplicada, mas não elimina vazamento entre experimentos correlacionados.
8. A otimização tem separação temporal, porém escolhe entre muitos perfis e usa critérios fixos. A janela final deve continuar intocada e promoção precisa ser auditável por versão.
9. Regras técnicas presentes são proxies simples: não há análise multi-timeframe, SessionEngine, validação geral de integridade/atraso dos candles, decisão estruturada completa nem journal imutável.
10. DPAPI só descriptografa no contexto Windows que protegeu o segredo. Uma configuração de Dukascopy protegida localmente não migra automaticamente para VM Linux.
11. A ponte MT5 tem token compartilhado e servidor HTTP serial; precisa de rotação/gestão de segredo, timeout, limites de taxa, health monitoring e política operacional de reinício.
12. Os executáveis/instaladores em `avulso/` são fontes não confiáveis e não fazem parte da aplicação ativa.
13. Os PDFs foram inventariados, mas não foi possível extrair texto/páginas nesta máquina. Regras existentes referenciam os resumos locais; as duas edições de Trading in the Zone e as páginas exatas ainda precisam de revisão humana.

## Execução e credenciais

Busca estática por `order_send` no código ativo não encontrou chamada de envio. A API rejeita qualquer modo diferente de `paper`; o feed e o provider MT5 são somente leitura. Nenhuma ordem foi enviada nesta auditoria. Há arquivos de segredo/token em `data/`; seus conteúdos não foram abertos nem incluídos neste documento. `.gitignore` os exclui, mas a inexistência de Git impede confirmar o histórico de publicação desta cópia.

## Informações pendentes

- corretora/símbolos autorizados, precisão, moeda da conta e propriedades de contrato por instrumento;
- fuso e definição das sessões a usar;
- fonte autorizada de calendário econômico, ou decisão explícita de não o usar;
- disponibilidade/licença e requisitos de replay/histórico para a fonte de dados escolhida;
- política de risco assinada pelo usuário (limites por trade/dia, exposição simultânea e bloqueios);
- interpretação/revisão das regras dos PDFs com seção/página precisa;
- ambiente-alvo de execução e armazenamento seguro de credenciais para Windows/VPS;
- configuração/versionamento do repositório Git antes de mudanças maiores.

## Primeiro vertical slice proposto

CSV histórico ou replay determinístico -> normalização e validação OHLC/timestamps/spread -> sessão UTC com timezone configurável -> pivôs/estrutura confirmados -> uma estratégia isolada de pullback -> decisão estruturada `NO_TRADE`/candidato -> RiskManager independente -> journal JSONL com IDs e versões -> relatório reproduzível. Execução real fica fora deste slice.
