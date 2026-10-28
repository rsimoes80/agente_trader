"""Serialize CPU text inference across the reader and specialists on this VM."""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[2]


@contextmanager
def model_slot(path=None):
    path=Path(path) if path else ROOT/'data/references_cache/literature-model.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as stream:
        path.chmod(0o600)
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def completion(payload, *, endpoint, timeout):
    # Queue time does not consume the HTTP inference timeout.
    with model_slot():
        request=Request(endpoint,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=timeout) as response:return json.load(response)
