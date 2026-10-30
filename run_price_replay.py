"""Seal/execute an isolated retrospective price experiment. Never connects to MT5."""
import argparse
import os
from pathlib import Path
import platform
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from aurelia_fx.offline_integrity import canonical,checked_files,decode,safe_file,sha256
from aurelia_fx.research_price.replay import load_rows,run,validate_protocol

ROOT=Path(__file__).resolve().parent
CODE=['run_price_replay.py','src/aurelia_fx/__init__.py','src/aurelia_fx/offline_integrity.py',
      'src/aurelia_fx/research_price/__init__.py','src/aurelia_fx/research_price/context.py',
      'src/aurelia_fx/research_price/execution.py','src/aurelia_fx/research_price/replay.py']


TESTS=['tests/unit/test_research_price.py','tests/unit/test_research_price_data.py']


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',required=True,type=Path)
    parser.add_argument('--protocol-sha256',required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--seal',action='store_true')
    mode.add_argument('--execute',action='store_true')
    parser.add_argument('--execution-seal-sha256')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:
        root=args.experiment.resolve();raw=safe_file(root,'protocol.json').read_bytes()
        if sha256(raw)!=args.protocol_sha256:
            raise ValueError('PROTOCOL_HASH_CHANGED')
        freeze=decode(safe_file(root,'freeze.json').read_bytes())
        checked_files(root,freeze['files'])
        if freeze['files'].get('protocol.json')!=args.protocol_sha256 or freeze.get('before_economic_results') is not True:
            raise ValueError('INVALID_PRE_RESULT_FREEZE')
        p=decode(raw);validate_protocol(p)
        rows,source=load_rows(p)
        code_hashes={n:sha256(safe_file(ROOT,n).read_bytes()) for n in CODE}
        test_hashes={n:sha256(safe_file(ROOT,n).read_bytes()) for n in TESTS}
        notes_hash=sha256(safe_file(root,'implementation_notes.md').read_bytes())
        if args.seal:
            if args.output or args.execution_seal_sha256:
                raise ValueError('SEAL_HAS_NO_RESULT_OUTPUT')
            seal=dict(protocol_sha256=args.protocol_sha256,freeze_sha256=sha256(safe_file(root,'freeze.json').read_bytes()),
                code_sha256=code_hashes,test_sha256=test_hashes,implementation_notes_sha256=notes_hash,
                source=source,python_version=platform.python_version(),
                status='SEALED_BEFORE_FIRST_ECONOMIC_EXECUTION',scope='research_only_no_trading_authority')
            os.umask(0o077)
            with (root/'execution_seal.json').open('xb') as f:f.write(canonical(seal))
            print(canonical(dict(status='SEALED',execution_seal_sha256=sha256(canonical(seal)),source=source)).decode())
            return 0
        seal_raw=safe_file(root,'execution_seal.json').read_bytes()
        if sha256(seal_raw)!=args.execution_seal_sha256:
            raise ValueError('EXECUTION_SEAL_HASH_CHANGED')
        seal=decode(seal_raw)
        if (seal['protocol_sha256']!=args.protocol_sha256 or seal['code_sha256']!=code_hashes or seal['source']!=source
                or seal['freeze_sha256']!=sha256(safe_file(root,'freeze.json').read_bytes())
                or seal['python_version']!=platform.python_version() or seal['test_sha256']!=test_hashes
                or seal['implementation_notes_sha256']!=notes_hash):
            raise ValueError('SEALED_INPUT_OR_CODE_CHANGED')
        if args.output is None:
            raise ValueError('NEW_OUTPUT_REQUIRED')
        output=args.output.resolve();input_root=Path(p['source']['bundle']).resolve()
        if (output.exists() or output==root or output.is_relative_to(input_root)
                or root.is_relative_to(output) or input_root.is_relative_to(output)):
            raise ValueError('OUTPUT_EXISTS_OR_OVERLAPS_INPUTS')
        result=run(rows,p)
        os.umask(0o077);output.mkdir(mode=0o700,exist_ok=False)
        (output/'result.json').write_bytes(canonical(result))
        summaries=[w['summary'] for w in result['partitions']]
        (output/'summary.json').write_bytes(canonical(dict(experiment_id=p['experiment_id'],partitions=summaries,
            interpretation=result['conclusions'])))
        for name in ['events','trades','decisions']:
            (output/(name+'.jsonl')).write_bytes(b''.join(canonical_line(dict(partition=w['summary']['name'],**e))
                for w in result['partitions'] for e in w[name]))
        lines=['# Replay econômico experimental de preço','',
            'Cenário retrospectivo, custos assumidos e volume centralizado ausente. Nenhuma autorização operacional.','',
            '| Janela | Operações | Encerradas | Censuradas | P&L conhecido parcial USD | P&L completo USD |',
            '|---|---:|---:|---:|---:|---:|']
        for s in summaries:
            lines.append(f"| {s['name']} | {s['trades']} | {s['closed']} | {s['censored']} | {s['known_outcome_partial_net_usd']:.2f} | {s['complete_net_usd']} |")
        lines+=['','Sem posições censuradas, o total ainda é apenas deste cenário fixo e tamanho constante. '
            'Com censura, a soma conhecida não é lucro total. Não houve ajuste após resultados; ambas as janelas são retrospectivas, sem holdout inédito.',
            '','Limites: OHLC bid e spread constante intrabar assumidos; custos não verificados no broker; '
            'disponibilidade histórica não demonstrada; transposição Forex M5 não validada; nenhuma inferência de modelo.','']
        (output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
        (output/'provenance.json').write_bytes(canonical(dict(protocol_sha256=args.protocol_sha256,
            execution_seal_sha256=args.execution_seal_sha256,source=source,code_sha256=code_hashes,
            test_sha256=test_hashes,implementation_notes_sha256=notes_hash)))
        (output/'artifact_hashes.json').write_bytes(canonical({f.name:sha256(f.read_bytes()) for f in sorted(output.iterdir())}))
        print(canonical(dict(status='RESEARCH_REPLAY_COMPLETED',output=str(output),partitions=summaries)).decode())
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(canonical(dict(status='FAILED_CLOSED',error=str(exc))).decode(),file=sys.stderr)
        return 2


def canonical_line(value):
    import json
    return (json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode()


if __name__=='__main__':
    raise SystemExit(main())
