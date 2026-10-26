"""Atomic, integrity-checked progress; incomplete writes never advance a cursor."""
import hashlib
import json
import os
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w',encoding='utf8') as stream:
        json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


class FeatureCheckpoint:
    def __init__(self, directory, phase, signature, shapes):
        import numpy as np
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.phase=phase;self.path=self.directory/(phase+'-checkpoint.json')
        self.signature=signature;self.completed=0
        saved=json.loads(self.path.read_text()) if self.path.exists() else None
        if saved and saved['signature']!=signature:raise ValueError('Feature checkpoint identity mismatch')
        self.arrays={}
        for name,shape in shapes.items():
            p=self.directory/(phase+'-'+name+'.npy')
            a=np.load(p,mmap_mode='r+',allow_pickle=False) if saved else np.lib.format.open_memmap(p,mode='w+',dtype='float32',shape=shape)
            if a.shape!=tuple(shape) or a.dtype!=np.dtype('float32'):raise ValueError('Feature checkpoint shape mismatch')
            self.arrays[name]=a
        if saved:
            self.completed=saved['completed']
            if not isinstance(self.completed,int) or not 0<=self.completed<=next(iter(shapes.values()))[0]:raise ValueError('Invalid feature cursor')
            if saved['hashes']!=self.hashes():raise ValueError('Feature checkpoint content mismatch')

    def hashes(self):
        return {name:hashlib.sha256(a[:self.completed].tobytes()).hexdigest() for name,a in self.arrays.items()}

    def commit(self, completed):
        if not self.completed<=completed<=len(next(iter(self.arrays.values()))):raise ValueError('Feature cursor cannot rewind')
        for a in self.arrays.values():a.flush()
        self.completed=completed
        atomic_json(self.path,dict(signature=self.signature,completed=completed,hashes=self.hashes()))


def save_epoch(path, payload, signature):
    import torch
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    torch.save(payload,temporary)
    with temporary.open('r+b') as stream:stream.flush();os.fsync(stream.fileno())
    sha=digest(temporary)
    immutable=path.with_name(path.stem+'.'+sha+path.suffix)
    os.replace(temporary,immutable)
    atomic_json(path.with_suffix('.json'),dict(signature=signature,sha256=sha))


def load_epoch(path, signature):
    import torch
    path=Path(path);meta=path.with_suffix('.json')
    if not meta.exists():return None
    record=json.loads(meta.read_text())
    sha=record['sha256']
    if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('Invalid epoch digest')
    immutable=path.with_name(path.stem+'.'+sha+path.suffix)
    if record['signature']!=signature or sha!=digest(immutable):raise ValueError('Epoch checkpoint integrity mismatch')
    return torch.load(immutable,map_location='cpu',weights_only=True)
