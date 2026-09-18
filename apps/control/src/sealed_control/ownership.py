"""OS advisory lock: the demo supports one control process per state directory."""
from pathlib import Path


class ProcessOwner:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a+b")
        try:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.unlock = lambda: fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        except ImportError:
            import msvcrt
            self.file.seek(0)
            if not self.file.read(1):
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            self.unlock = lambda: (self.file.seek(0), msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1))
        except OSError as exc:
            self.file.close()
            raise RuntimeError("control_already_owned") from exc

    def close(self):
        self.unlock()
        self.file.close()
