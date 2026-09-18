#!/usr/bin/env python3
"""Local Compose launcher with explicit, authoritative planner selection."""

from __future__ import annotations

import getpass
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env.local"
OLLAMA_HOST = "http://127.0.0.1:11434"
COMPOSE_BASE = "http://host.docker.internal:11434/v1"
GIB = 1024**3
PROVIDER_KEYS = ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")

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


def dotenv_value(value: str) -> str:
    if any(character in value for character in ("\n", "\r", "\0")):
        raise ValueError("Configuration values must be a single line without NUL characters.")
    # Compose expands double-quoted escapes and recognizes \$ as a literal
    # dollar. JSON escaping also preserves trailing backslashes and quotes.
    return json.dumps(value, ensure_ascii=False).replace("$", "\\$")


def write_env(values: dict[str, str]) -> None:
    lines = []
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Invalid configuration key.")
        lines.append(f"{key}={dotenv_value(value)}")
    content = "\n".join(lines) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".env.local-", dir=ENV_FILE.parent)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, ENV_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    say(f"Wrote {ENV_FILE.name}")


def run_compose(config: dict[str, str]) -> int:
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
    for key in PROVIDER_KEYS:
        env.pop(key, None)
    # Explicit values override shell precedence as well as the dotenv file.
    env.update(config)
    try:
        return subprocess.call(cmd, cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError:
        say("docker not found on PATH.")
        return 1


def planner_config(mode: str, **values: str) -> dict[str, str]:
    return {"PLANNER": mode, "ALLOW_PLANNER_NETWORK": "false" if mode == "stub" else "true", **{key: "" for key in PROVIDER_KEYS}, **values}


def launch(config: dict[str, str]) -> int:
    write_env(config)
    return run_compose(config)


def path_stub() -> int:
    return launch(planner_config("stub"))


def path_xai(*, interactive: bool = False, model: str | None = None) -> int:
    key = os.environ.get("XAI_API_KEY", "")
    dotenv_value(key)
    key = key.strip()
    if not key and interactive:
        key = ask("xAI API key", password=True).strip()
    if not key:
        say("XAI_API_KEY is required for --xai. Set it in the environment or choose --stub.")
        return 2
    return launch(planner_config("xai", XAI_API_KEY=key, LLM_MODEL=model or "grok-4.5"))


def path_llama(*, interactive: bool = False, model: str | None = None) -> int:
    system = platform.system()
    kind = arch()
    ram = ram_bytes()
    ram_gib = (ram / GIB) if ram else None
    say(f"OS={system} arch={kind} RAM={ram_gib:.1f} GiB" if ram_gib else f"OS={system} arch={kind} RAM=unknown")

    if not arch_ok(kind):
        say(f"Arch {kind} is unsupported for this launcher.")
        if interactive and confirm("Continue with stub planner?", default=True):
            return path_stub()
        return 1

    if ram is not None and ram < 8 * GIB:
        say(f"Need at least 8 GiB RAM for local Llama (saw {ram_gib:.1f} GiB).")
        if interactive and confirm("Continue with stub planner?", default=True):
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
        if interactive and confirm("Continue with stub planner?", default=True):
            return path_stub()
        return 1

    models = ollama_models()
    if models:
        say("Installed models: " + ", ".join(models))
    else:
        say("No Ollama models installed yet.")

    recommend = "llama3.2" if ram is None or ram < 16 * GIB else "llama3.1"
    say(f"Recommend: {recommend}")
    if not model:
        model = ask("Model", default=recommend).strip() if interactive else "llama3.2"
        model = model or recommend

    if not has_model(models, model):
        if interactive and confirm(f"Run ollama pull {model}?", default=False):
            code = subprocess.call([binary, "pull", model])
            if code != 0:
                say("pull failed. Using stub.")
                return path_stub()
        else:
            say(f"Model is not installed. Install the selected model with Ollama, then retry --llama --model {model}, or use --stub.")
            return 2

    return launch(planner_config("llama", LLM_BASE_URL=COMPOSE_BASE, LLM_MODEL=model, LLM_API_KEY="ollama"))


def menu() -> str:
    panel(
        "1  stub planner (demo, no LLM)\n"
        "2  llama (Ollama on this machine)\n"
        "3  xai (optional planner-only API access)",
        title="How should the planner run?",
    )
    choice = ask("Choice", default="1").strip()
    return choice


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the local Sealed Compose demo. Stub mode works without a model provider.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stub", dest="mode", action="store_const", const="stub", help="Use the offline deterministic planner; ignore inherited provider settings.")
    mode.add_argument("--llama", dest="mode", action="store_const", const="llama", help="Use an installed Ollama model through the explicit planner-only host exception.")
    mode.add_argument("--xai", dest="mode", action="store_const", const="xai", help="Use optional xAI planning; requires XAI_API_KEY in the environment.")
    parser.add_argument("--model", help="Installed Ollama model or xAI model name; never an injection target.")
    args = parser.parse_args(argv)
    if args.model and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", args.model):
        parser.error("--model must be a valid model name (up to 128 characters).")
    if args.model and args.mode not in {"llama", "xai"}:
        parser.error("--model requires --llama or --xai.")
    interactive = args.mode is None and sys.stdin.isatty()
    choice = args.mode or (menu() if interactive else "stub")
    try:
        if choice in {"1", "stub"}:
            return path_stub()
        if choice in {"2", "llama"}:
            return path_llama(interactive=interactive, model=args.model)
        if choice in {"3", "xai"}:
            return path_xai(interactive=interactive, model=args.model)
    except ValueError as exc:
        say(str(exc))
        return 2
    say("Unknown choice.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
