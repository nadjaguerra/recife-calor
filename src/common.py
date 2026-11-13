"""Shared paths, atomic writes and scientific transformations."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
PROCESSED = ROOT / 'data' / 'processed'
OUTPUT = ROOT / 'outputs'


def setup():
    for folder in (RAW / 'scenes', PROCESSED, OUTPUT / 'maps', OUTPUT / 'models'):
        folder.mkdir(parents=True, exist_ok=True)


def config():
    return json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def temperature_c(dn):
    return np.asarray(dn, dtype=np.float32) * 0.00341802 + 149 - 273.15


def reflectance(dn):
    return np.asarray(dn, dtype=np.float32) * 0.0000275 - 0.2


def normalized_difference(a, b):
    denominator = a + b
    return np.divide(a - b, denominator, out=np.full_like(a, np.nan), where=np.abs(denominator) > 1e-6)


def clear_land(qa, saturation):
    # Fill, dilated cloud, cirrus, cloud, shadow, snow and water excluded.
    return ((qa.astype(np.uint16) & 191) == 0) & (saturation == 0)


def block_reduce(array, factor=4, minimum=0.75):
    h, w = array.shape
    blocks = array.reshape(h // factor, factor, w // factor, factor)
    valid = np.isfinite(blocks)
    count = valid.sum(axis=(1, 3))
    total = np.where(valid, blocks, 0).sum(axis=(1, 3))
    result = np.divide(total, count, out=np.full(count.shape, np.nan, dtype=np.float32), where=count > 0)
    result[count < factor * factor * minimum] = np.nan
    return result


@contextmanager
def pipeline_lock():
    """OS lock is released even if Python or the machine is interrupted."""
    setup()
    handle = (RAW/'pipeline.lock').open('a+b')
    handle.seek(0,2)
    if handle.tell()==0:
        handle.write(b'0');handle.flush()
    handle.seek(0)
    acquired=False
    try:
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError as error:
            raise RuntimeError('Já existe uma coleta em andamento nesta pasta.') from error
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()


def pipeline_is_running():
    try:
        with pipeline_lock():
            return False
    except RuntimeError:
        return True
