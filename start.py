#!/usr/bin/env python3
"""Interactive Sealed launcher. Writes .env.local then docker compose up --build."""

from __future__ import annotations

import getpass
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env.local"
OLLAMA_HOST = "http://127.0.0.1:11434"
COMPOSE_BASE = "http://host.docker.internal:11434/v1"
GIB = 1024**3

INSTALL = {
    "Windows": "https://ollama.com/download/windows",
    "Darwin": "https://ollama.com/download/mac",
    "Linux": "https://ollama.com/download/linux",
}

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt

    _CONSOLE = Console()
    _RICH = True
except ImportError:
    _CONSOLE = None
    _RICH = False


def say(text: str) -> None:
    if _RICH:
        _CONSOLE.print(text)
    else:
        print(text)


def panel(text: str, title: str = "Sealed") -> None:
    if _RICH:
        _CONSOLE.print(Panel(text, title=title))
    else:
        print(f"--- {title} ---\n{text}\n")


def ask(text: str, *, default: str | None = None, password: bool = False) -> str:
    if password:
        if _RICH:
            return Prompt.ask(text, password=True)
        return getpass.getpass(f"{text}: ")
    if _RICH:
        kwargs = {}
        if default is not None:
            kwargs["default"] = default
        return Prompt.ask(text, **kwargs)
    hint = f" [{default}]" if default is not None else ""
    value = input(f"{text}{hint}: ").strip()
    return value or (default or "")


def confirm(text: str, *, default: bool = True) -> bool:
    if _RICH:
        return Confirm.ask(text, default=default)
    suffix = " [Y/n] " if default else " [y/N] "
    value = input(text + suffix).strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def arch() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


def arch_ok(kind: str) -> bool:
    return kind in {"amd64", "arm64"}


def ram_bytes() -> int | None:
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().total)
    except Exception:
        pass
    system = platform.system()
    try:
        if system == "Linux":
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb * 1024
        if system == "Darwin":
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True
            ).strip()
            return int(out)
        if system == "Windows":
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
                ],
                text=True,
            ).strip()
            return int(out)
    except Exception:
        return None
    return None


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_HOST, timeout=2) as resp:
            return resp.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ollama_models() -> list[str]:
    names: list[str] = []
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5) as resp:
            import json

            data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("models") or []:
                name = str(item.get("name") or "")
                if name:
                    names.append(name)
            return names
    except Exception:
        pass
    binary = shutil.which("ollama")
    if not binary:
        return names
    try:
        out = subprocess.check_output([binary, "list"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return names
    for line in out.splitlines()[1:]:
        part = line.split()
        if part:
            names.append(part[0])
    return names


def has_model(models: list[str], want: str) -> bool:
    want = want.lower()
    for name in models:
        low = name.lower()
        if low == want or low.startswith(want + ":"):
            return True
    return False


def write_env(lines: list[str]) -> None:
    ENV_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(ENV_FILE, 0o600)
        except OSError:
            pass
    say(f"Wrote {ENV_FILE.name}")


def run_compose() -> int:
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "up",
        "--build",
    ]
    say(" ".join(cmd))
    env = os.environ.copy()
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key] = value
    try:
        return subprocess.call(cmd, cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError:
        say("docker not found on PATH.")
        return 1


def path_stub() -> int:
    write_env(["PLANNER=stub"])
    return run_compose()


def path_xai() -> int:
    key = ask("xAI API key", password=True).strip()
    if not key:
        say("No key entered. Using stub.")
        return path_stub()
    write_env([f"XAI_API_KEY={key}"])
    return run_compose()


def path_llama() -> int:
    system = platform.system()
    kind = arch()
    ram = ram_bytes()
    ram_gib = (ram / GIB) if ram else None
    say(f"OS={system} arch={kind} RAM={ram_gib:.1f} GiB" if ram_gib else f"OS={system} arch={kind} RAM=unknown")

    if not arch_ok(kind):
        say(f"Arch {kind} is unsupported for this launcher.")
        if confirm("Continue with stub planner?", default=True):
            return path_stub()
        return 1

    if ram is not None and ram < 8 * GIB:
        say(f"Need at least 8 GiB RAM for local Llama (saw {ram_gib:.1f} GiB).")
        if confirm("Continue with stub planner?", default=True):
            return path_stub()
        return 1

    binary = shutil.which("ollama")
    up = ollama_up()
    if not binary or not up:
        link = INSTALL.get(system, "https://ollama.com/download")
        if not binary:
            say("ollama is not on PATH.")
        else:
            say("ollama binary found but nothing is listening on 127.0.0.1:11434.")
            say("Start it with: ollama serve")
        say(f"Install: {link}")
        say("This launcher does not download Ollama.")
        if confirm("Continue with stub planner?", default=True):
            return path_stub()
        return 1

    models = ollama_models()
    if models:
        say("Installed models: " + ", ".join(models))
    else:
        say("No Ollama models installed yet.")

    recommend = "llama3.2" if ram is None or ram < 16 * GIB else "llama3.1"
    say(f"Recommend: {recommend}")
    model = ask("Model", default=recommend).strip() or recommend

    if not has_model(models, model):
        if confirm(f"Run ollama pull {model}?", default=True):
            code = subprocess.call([binary, "pull", model])
            if code != 0:
                say("pull failed. Using stub.")
                return path_stub()
        else:
            say("No pull. Using stub.")
            return path_stub()

    write_env(
        [
            f"LLM_BASE_URL={COMPOSE_BASE}",
            f"LLM_MODEL={model}",
            "LLM_API_KEY=ollama",
        ]
    )
    return run_compose()


def menu() -> str:
    panel(
        "1  stub planner (demo, no LLM)\n"
        "2  llama (Ollama on this machine)\n"
        "3  xai (SpaceXAI API key)",
        title="How should the planner run?",
    )
    choice = ask("Choice", default="1").strip()
    return choice


def main() -> int:
    os.chdir(ROOT)
    choice = menu()
    if choice in {"1", "stub"}:
        return path_stub()
    if choice in {"2", "llama"}:
        return path_llama()
    if choice in {"3", "xai"}:
        return path_xai()
    say("Unknown choice.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
