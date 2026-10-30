"""Private, immutable review inputs; this module has no execution authority."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .book_specialists import validate_case
from .literature_learning import redact

UPSTREAM_REVISION='403d8881d62022490637d740657b33f01e321ea8'
PAGES=(6,7,8,9,10,12,15,17,24)
CODE=('agent_strategy.py','entry_trend.py','literature_basis.py')


def file_sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def prepare(root,case):
    root=Path(root);validate_case(case)
    cache=root/'data/references_cache/learning-library'
    sources=json.loads((cache/'inventory.json').read_text())
    source=next(s for s in sources if s['document']=='EBOOK-MANUAL-DO-PULLBACK.pdf')
    if file_sha(root/'Aprendizado'/source['document'])!=source['sha256']:raise ValueError('REVIEW_PDF_CHANGED')
    pages=[]
    for number in PAGES:
        page=json.loads((root/source['cache']/f'{number:04d}.json').read_text())
        if hashlib.sha256(page['text'].encode()).hexdigest()!=page['text_sha256']:raise ValueError('REVIEW_PAGE_CHANGED')
        pages.append(dict(pdf_page=number,text=redact(page['text']),original_text_sha256=page['text_sha256'],
                          method=page['method'],visual_reviewed=False))
    folder=root/'data/reports/egm'/('pullback-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True,mode=0o700)
    def write(name,body):
        path=folder/name;path.write_text(body,encoding='utf-8');path.chmod(0o600)
    write('case.json',json.dumps(case,ensure_ascii=False,indent=2)+'\n')
    write('sources.json',json.dumps(dict(document=source['document'],pdf_sha256=source['sha256'],pages=pages),ensure_ascii=False,indent=2)+'\n')
    for name in CODE:write('code_'+name+'.txt',(root/'src/aurelia_fx'/name).read_text())
    draft=f'''# Hipótese de pesquisa: pullback comprador em tendência H1

Estado: rascunho para revisão. Nenhuma regra deste documento autoriza ordens.
Caso congelado: `{case['case_id']}`. As of UTC: `{case['as_of']}`.
Ativo: {case['symbol']}. Direção registrada no caso: {case['side']}.
Se o caso não tiver tendência compradora H1 confirmada, a hipótese não é elegível
nesse caso. Não altere a direção nem substitua o caso para obter uma entrada.

## Intenção e fontes

Avaliar uma hipótese compradora a favor da tendência. A política H1 é requisito
do operador. Não generalizamos automaticamente o texto para operações vendidas.
As páginas são físicas do PDF; o texto está em sources.json. As figuras não foram
incluídas visualmente. O texto do autor não comprova validade no Forex M5.

## Regras propostas, ainda não implementadas como este método

1. Contexto: tendência compradora H1 confirmada. A confirmação atual é cálculo
do sistema e requer validação própria, sem atribuí-la universalmente ao livro.
2. Correção: avaliar profundidade relativa, velocidade, volume e estrutura
(Manual pp. 6–10). Volume negociado centralizado está ausente no Forex de ticks;
não declarar os quatro critérios atendidos. A relação entre a quantidade de
critérios e o tamanho da posição exige resolver a adaptação, preservando os
limites de risco do projeto; não autoriza variar o lote nesta etapa.
3. Região: identificar uma região pertinente e sua eventual confluência (p. 12).
Ainda falta especificar algoritmos e tolerâncias de identificação causal.
4. Gatilho: estudar rompimento da máxima do candle de confirmação na região
(p. 15), sem antecipação. É pendente definir ordem, validade, preço executável,
spread e tratamento de gap; o pacote não contém cotação bid/ask histórica completa.
5. Invalidação: mínima estrutural da correção, sem encurtar o stop para caber
posição (p. 17). Delimitação da correção e margem de execução estão pendentes.
6. Saída: primeiro obstáculo no topo anterior, com o critério textual de retorno
mínimo do autor na p. 17. A relação líquida após custos precisa de avaliação
separada. Não substituir silenciosamente por múltiplo fixo de ATR ou alvo 2,5R.

## Código fornecido para comparação

code_agent_strategy.py.txt é um snapshot da hipótese anterior de pesquisa, com
EMA21, ATR14, stop dos três candles e alvo 2,5R. Não implementa integralmente as
regras acima. code_entry_trend.py.txt contém o guard de direção/base bibliográfica;
code_literature_basis.py.txt verifica referências e registro de aprovação.
Estes três arquivos não representam auditoria de todos os caminhos de execução.

## Evidências ausentes e validação necessária

case.json contém contexto calculado e uma janela curta de M5, não uma reconstrução
independente de todo H1/H4 nem uma série completa de impulsos e correções.
Ainda faltam revisão visual, especificação dos algoritmos, tolerâncias, custos,
tratamento de spread/slippage e replay com janela separada. Não usar resultados
futuros para escolher uma interpretação. Não atribuir probabilidade de lucro à
concordância dos revisores. Não há benchmark ou rentabilidade demonstrada.

## Escopo desta rodada

Duas revisões somente leitura, uma rodada, fontes/testabilidade e correspondência
com o código. Propor correções; não editar fichas, pesos, estratégia, serviços,
registro de aprovação ou estado de negociação. A revisão não implica implantação.
'''
    write('hypothesis.md',draft)
    files={p.name:file_sha(p) for p in folder.iterdir() if p.is_file()}
    manifest=dict(schema_version=1,case_id=case['case_id'],as_of=case['as_of'],files=files,
                  upstream_repository='https://github.com/google/elephant-goldfish-model',upstream_revision=UPSTREAM_REVISION,
                  review_roles=['source-fidelity','implementation-fidelity'],max_reviewers=2,max_rounds=1,
                  status='prepared_not_reviewed',trading_authority=False)
    write('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return folder


def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    expected={'case.json','sources.json','hypothesis.md',*('code_'+name+'.txt' for name in CODE)}
    if (manifest.get('schema_version')!=1 or manifest.get('trading_authority') is not False
            or not isinstance(manifest.get('files'),dict) or set(manifest['files'])!=expected):
        raise ValueError('REVIEW_MANIFEST_INVALID')
    for name,sha in manifest['files'].items():
        if Path(name).name!=name or file_sha(folder/name)!=sha:raise ValueError('REVIEW_INPUT_CHANGED')
    case=json.loads((folder/'case.json').read_text());validate_case(case)
    if any(manifest[k]!=case[k] for k in ('case_id','as_of')):raise ValueError('REVIEW_CASE_MISMATCH')
    return manifest
