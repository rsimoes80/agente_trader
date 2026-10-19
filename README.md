# Aurelia FX

Interface local para análise de Forex em tempo real, com painel em português, filtros configuráveis, gestão de risco e arquitetura para múltiplos provedores.

## Iniciar

No PowerShell, dentro desta pasta:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Abra <http://127.0.0.1:8768>. O servidor aceita conexões somente deste computador.

Para visualizar o gráfico EUR/USD no estilo do MT5, abra **Gráfico EUR/USD** no menu lateral ou acesse <http://127.0.0.1:8768/chart.html>. A página usa o terminal MT5 local para exibir candles, cotação bid/ask e EMA 21; funciona em modo somente leitura.

## Página publicada na VM Linux

A visualização do gráfico está publicada na VM `svrdev`: <http://192.168.97.221:8097/>. O container `aurelia-fx-chart` serve `static/chart.html`, `static/chart.css` e `static/chart.js`; a configuração do proxy Nginx está em [deploy/vm/nginx-chart.conf](deploy/vm/nginx-chart.conf).

O gráfico recebe candles M5, EMA 21 e bid/ask do terminal MT5 demo no Windows por meio da ponte somente leitura [mt5_bridge.py](mt5_bridge.py), escutando no adaptador privado `192.168.200.1:8769`. Para iniciar/reiniciar a ponte manualmente, execute `.\run_mt5_bridge.ps1` no PowerShell deste projeto. A sessão Windows e o terminal MT5 precisam permanecer ligados e conectados. A página não envia ordens. O endereço publicado usa o IP privado da VM e depende da mesma rede/VPN.

## Recursos

- Replay causal do EUR/USD com memória SQLite, contratos de expectativa, veto de risco e relatório HTML por execução. Execute `python run_replay.py --capture-mt5 --count 1500` ou use um CSV histórico. Consulte [docs/replay.md](docs/replay.md).

- Painel visual em português para estratégia, risco, provedores, monitoramento e pesquisa.
- Feed Dukascopy FIX 4.4 somente para leitura: cotações bid/ask e candles montados a partir dos dados ao vivo. A análise é refeita no fechamento de cada candle. Consulte [DUKASCOPY_FIX.md](DUKASCOPY_FIX.md).
- Captura de histórico e validação temporal 70/30 usando candles reais do terminal MetaTrader 5 local, em modo somente leitura. Requer Windows, MetaTrader 5 aberto e conectado. Os 30% finais ficam fora do aprendizado.
- Gráfico EUR/USD integrado ao painel Aurelia FX, com períodos selecionáveis, candles históricos do MT5, bid/ask atualizado e EMA 21. Consulte [DOC_METATRADER5_PYTHON.md](DOC_METATRADER5_PYTHON.md) para a referência da integração Python.
- Indicadores EMA, RSI, MACD, ADX e ATR, além de pivôs, retrações, BOS, varredura de liquidez e qualidade de pullback.
- TA-Lib para reconhecimento de nove padrões de candles. Um padrão alinhado à direção candidata pode contar como uma confluência; padrões isolados não geram sinal.
- Revisão opcional pelo JEV. O modelo recebe o padrão reconhecido e o contexto técnico para avaliar se é coerente; uma resposta de espera bloqueia a recomendação.
- Backtest CSV OHLCV para validação de estratégia, sem ser necessário para o monitor ao vivo.
- Configurações de risco, stops estruturais, limites diários e controle de drawdown.
- Credenciais salvas localmente com DPAPI do Windows; os segredos não são exibidos após o salvamento.
- NautilusTrader instalado neste projeto para pesquisa de integração. Consulte [INTEGRATION_NAUTILUS.md](INTEGRATION_NAUTILUS.md).

## Limites atuais

O feed Dukascopy FIX requer que a corretora habilite os parâmetros da conta e autorize o IP. O sistema continua em modo de demonstração: não envia ordens. A integração de execução e reconciliação de ordens não está habilitada.

A biblioteca Python oficial do MT5 comunica-se com um terminal local Windows. Para um projeto hospedado em Linux, será necessário executar um serviço ponte no Windows onde o MT5 está aberto; a validação MT5 desta instalação está habilitada no Windows.

TA-Lib fornece cálculos técnicos e detectores de padrões de candles; não é por si só um sistema completo de price action. O score é uma contagem de condições, não uma probabilidade de ganho. Padrões devem ser avaliados no contexto de tendência, volatilidade, localização e estrutura; o JEV é uma segunda opinião e não garante resultado.

## Persistência local

- Configurações: `data/user_config.json`.
- Credenciais criptografadas: `data/credentials.dpapi`.
- O ambiente `.venv/` e as credenciais devem permanecer fora do controle de versão.
- Calibração controlada de oito perfis no histórico MT5: usa 70% para ajuste e reserva 30% final para validação. Um modelo só é promovido se o período reservado tiver pelo menos 30 operações, acerto mínimo de 70%, fator de lucro mínimo 1 e modelo adaptativo aprovado. Caso contrário, a configuração atual é mantida.
