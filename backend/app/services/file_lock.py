from __future__ import annotations

import threading
from contextlib import contextmanager

_LOCKS: dict[int, threading.RLock] = {}
_GUARD = threading.Lock()


@contextmanager
def file_lock(file_id: int):
    with _GUARD:
        lock = _LOCKS.setdefault(int(file_id), threading.RLock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()