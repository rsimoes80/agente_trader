"""Install pinned llama.cpp CUDA 12 for Pascal-compatible WSL GPU inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parent
RELEASE='b11962'
ASSETS={
 'llama-b11962-bin-ubuntu-cuda-12.8-x64.tar.gz':'a958bb048daedae1afcf3d671dbd9fd8880bdbab01c05a89d1991dcb26e7220d',
 'cudart-llama-b11962-bin-ubuntu-cuda-12.8-x64.tar.gz':'887891567a962026e8eb4430e2e95b169bc8f00cf883ae2f68ce6250005236f9',
}


def sha256(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layers',type=int,default=24)
    args=parser.parse_args()
    if not 1<=args.layers<=36:parser.error('Use 1..36 offloaded layers')
    smi=Path('/usr/lib/wsl/lib/nvidia-smi')
    if not Path('/dev/dxg').exists() or not smi.exists():raise SystemExit('WSL_GPU_NOT_EXPOSED')
    result=subprocess.run([str(smi),'--query-gpu=name,memory.total,driver_version,compute_cap','--format=csv,noheader,nounits'],
                          capture_output=True,text=True,check=True,timeout=10)
    print(result.stdout.strip())
    # Runtime-only libraries: never install a Linux NVIDIA driver inside WSL.
    destination=ROOT/'.tools/llama-cuda12';destination.mkdir(parents=True,exist_ok=True)
    for name,digest in ASSETS.items():
        archive=destination/name
        if not archive.exists():
            temporary=archive.with_suffix('.download')
            urllib.request.urlretrieve(f'https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{name}',temporary)
            temporary.replace(archive)
        if sha256(archive)!=digest:raise SystemExit('CUDA_ASSET_HASH_MISMATCH: '+name)
        with tarfile.open(archive) as stream:stream.extractall(destination,filter='data')
    binary=destination/'llama-b11962/llama-server'
    libraries=':'.join(str(p) for p in (destination/'cudart-llama-b11962-bin-ubuntu-cuda-12.8-x64',
                                      destination/'llama-b11962',ROOT/'.tools/tesseract/usr/lib/x86_64-linux-gnu',Path('/usr/lib/wsl/lib')))
    probe=subprocess.run([str(binary),'--list-devices'],env={**os.environ,'LD_LIBRARY_PATH':libraries},capture_output=True,text=True,check=True)
    if 'CUDA0:' not in probe.stdout+probe.stderr:raise SystemExit('CUDA_BACKEND_NOT_AVAILABLE')
    print(probe.stdout.strip())
    def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    command=[binary,'--model',ROOT/'data/models/literature-reader/Qwen3-4B-Q4_K_M.gguf',
             '--host','127.0.0.1','--port','8791','--ctx-size','8192','--parallel','1',
             '--threads','2','--threads-batch','2','--batch-size','256','--ubatch-size','64',
             '--n-gpu-layers',str(args.layers),'--device','CUDA0','--chat-template-kwargs','{"enable_thinking":false}']
    dropins=Path.home()/'.config/systemd/user/agente-trader-literature-model.service.d';dropins.mkdir(parents=True,exist_ok=True)
    # Preserve resource ceilings; GPU acceleration does not replace host RAM safeguards.
    (dropins/'resource-limits.conf').write_text((ROOT/'deploy/linux/literature-model-resource-limits.conf').read_text())
    (dropins/'zz-cuda.conf').write_text('[Service]\nEnvironment='+quote('LD_LIBRARY_PATH='+libraries)+'\nExecStart=\nExecStart='+' '.join(quote(x) for x in command)+'\n')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemd-analyze','--user','verify',str(Path.home()/'.config/systemd/user/agente-trader-literature-model.service')],check=True)
    runtime=dict(backend='CUDA',runtime='llama.cpp',release=RELEASE,cuda_runtime='12.8',offloaded_layers=args.layers,
                 context=8192,batch_size=256,ubatch_size=64,threads=2,assets=ASSETS,device='CUDA0',
                 gpu=result.stdout.strip(),full_project_on_gpu=False)
    path=ROOT/'data/references_cache/literature-runtime.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(runtime,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)
    subprocess.run(['systemctl','--user','restart','agente-trader-literature-model.service'],check=True)
    print('CUDA configured. Validate /health, a completion and nvidia-smi before resuming research workers.')


if __name__=='__main__':main()
