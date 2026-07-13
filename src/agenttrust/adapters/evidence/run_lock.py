"""Cross-platform, re-entrant lock for one evidence run directory."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from threading import RLock
from time import monotonic, sleep
from typing import BinaryIO


class RunLock:
    """Serialize mutations and state transitions for one run across processes."""

    def __init__(self, run_dir: Path, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be zero or greater")
        self._path = run_dir / ".run.lock"
        self._timeout_seconds = timeout_seconds
        self._mutex = RLock()
        self._handle: BinaryIO | None = None
        self._depth = 0

    def __enter__(self) -> RunLock:
        return self.acquire()

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.release()

    def acquire(self) -> RunLock:
        with self._mutex:
            if self._depth:
                self._depth += 1
                return self
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._path.open("a+b")
            _ensure_lock_byte(handle)
            deadline = monotonic() + self._timeout_seconds
            while True:
                try:
                    _try_lock(handle)
                    self._handle = handle
                    self._depth = 1
                    return self
                except OSError:
                    if monotonic() >= deadline:
                        handle.close()
                        raise TimeoutError(f"timed out waiting for run lock: {self._path}") from None
                    sleep(0.02)

    def release(self) -> None:
        with self._mutex:
            if self._depth == 0:
                raise RuntimeError("run lock is not held")
            self._depth -= 1
            if self._depth:
                return
            assert self._handle is not None
            try:
                _unlock(self._handle)
            finally:
                self._handle.close()
                self._handle = None


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)


def _try_lock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
