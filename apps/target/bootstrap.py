"""Initialize the private Compose credential before starting the target owner."""

from __future__ import annotations

import os
from pathlib import Path
import re
import secrets


def initialize_credential(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(secrets.token_hex(32) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    if not re.fullmatch(r"[0-9a-f]{64}", path.read_text(encoding="ascii").strip()):
        raise RuntimeError("Invalid server credential file; restore the private auth volume")
    path.chmod(0o600)


if __name__ == "__main__":
    filename = os.environ.get("UNSEAL_TOKEN_FILE")
    if not filename:
        raise RuntimeError("UNSEAL_TOKEN_FILE must name the private Compose credential")
    initialize_credential(Path(filename))
    os.execvp("uvicorn", ["uvicorn", "sealed_target.main:app", "--host", "0.0.0.0",
                          "--port", "8080", "--workers", "1"])
