"""An OS lock prevents multiple target processes sharing the local fault state."""

from pathlib import Path


class ProcessOwner:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a+b")
        try:
            try:
                import fcntl
            except ImportError:
                import msvcrt
                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                self.unlock = lambda: (self.file.seek(0), msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1))
            else:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.unlock = lambda: fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            self.file.close()
            raise RuntimeError("target_requires_single_process") from exc

    def close(self) -> None:
        self.unlock()
        self.file.close()
