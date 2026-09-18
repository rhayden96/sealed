"""Launcher tests never start Compose, contact providers, or download models."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import start


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    monkeypatch.setattr(start, "ROOT", tmp_path)
    monkeypatch.setattr(start, "ENV_FILE", tmp_path / ".env.local")
    monkeypatch.setattr(start, "ask", lambda *args, **kwargs: pytest.fail("noninteractive mode prompted"))
    monkeypatch.setattr(start, "confirm", lambda *args, **kwargs: pytest.fail("noninteractive mode prompted"))
    calls = []
    monkeypatch.setattr(start.subprocess, "call", lambda command, **kwargs: calls.append((command, kwargs)) or 0)
    return calls


def test_stub_is_authoritative_over_inherited_provider_settings(launcher, monkeypatch):
    for key in start.PROVIDER_KEYS:
        monkeypatch.setenv(key, "sensitive-inherited-value")
    monkeypatch.setenv("PLANNER", "xai")
    monkeypatch.setenv("ALLOW_PLANNER_NETWORK", "true")
    monkeypatch.setattr(start, "ollama_up", lambda: pytest.fail("stub contacted provider"))
    assert start.main(["--stub"]) == 0
    command, options = launcher[0]
    assert command[:2] == ["docker", "compose"]
    assert options["env"]["PLANNER"] == "stub"
    assert options["env"]["ALLOW_PLANNER_NETWORK"] == "false"
    assert all(options["env"].get(key, "") == "" for key in start.PROVIDER_KEYS)
    assert "sensitive-inherited-value" not in start.ENV_FILE.read_text()


def test_xai_requires_environment_key_without_prompt_or_secret_output(launcher, monkeypatch, capsys):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert start.main(["--xai"]) == 2
    assert launcher == []
    key = "fake-$literal # 'quoted' \\\"key"
    monkeypatch.setenv("XAI_API_KEY", key)
    assert start.main(["--xai", "--model", "grok-4.5"]) == 0
    assert launcher[0][1]["env"]["XAI_API_KEY"] == key
    assert launcher[0][1]["env"]["PLANNER"] == "xai"
    assert launcher[0][1]["env"]["ALLOW_PLANNER_NETWORK"] == "true"
    assert key not in capsys.readouterr().out


def test_llama_installed_model_noninteractive_and_no_download(launcher, monkeypatch):
    monkeypatch.setattr(start, "arch", lambda: "amd64")
    monkeypatch.setattr(start, "ram_bytes", lambda: 16 * start.GIB)
    monkeypatch.setattr(start.shutil, "which", lambda executable: executable)
    monkeypatch.setattr(start, "ollama_up", lambda: True)
    monkeypatch.setattr(start, "ollama_models", lambda: ["llama3.2:latest"])
    assert start.main(["--llama", "--model", "llama3.2"]) == 0
    assert len(launcher) == 1 and launcher[0][0][:2] == ["docker", "compose"]
    assert launcher[0][1]["env"]["PLANNER"] == "llama"
    assert launcher[0][1]["env"]["LLM_BASE_URL"] == start.COMPOSE_BASE


def test_missing_llama_model_does_not_download_or_silently_fallback(launcher, monkeypatch):
    monkeypatch.setattr(start, "arch", lambda: "amd64")
    monkeypatch.setattr(start, "ram_bytes", lambda: 16 * start.GIB)
    monkeypatch.setattr(start.shutil, "which", lambda executable: executable)
    monkeypatch.setattr(start, "ollama_up", lambda: True)
    monkeypatch.setattr(start, "ollama_models", lambda: [])
    assert start.main(["--llama"]) == 2
    assert launcher == []


@pytest.mark.parametrize("arguments", [["--help"], ["--stub", "--xai"], ["--stub", "--model", "x"], ["--llama", "--model", "model\ninjected=value"]])
def test_cli_help_and_invalid_flags_have_no_side_effects(launcher, arguments):
    with pytest.raises(SystemExit) as result:
        start.main(arguments)
    assert result.value.code == (0 if arguments == ["--help"] else 2)
    assert launcher == []
    assert not start.ENV_FILE.exists()


@pytest.mark.parametrize("value", ["secret\nPLANNER=xai", "secret\rnew", "secret\0hidden"])
def test_dotenv_rejects_control_characters_before_replacing_file(launcher, value):
    start.ENV_FILE.write_text("original")
    with pytest.raises(ValueError, match="single line"):
        start.write_env({"XAI_API_KEY": value})
    assert start.ENV_FILE.read_text() == "original"
    assert list(start.ENV_FILE.parent.glob(".env.local-*")) == []


def test_failed_atomic_replace_preserves_previous_config_and_cleans_temp(launcher, monkeypatch):
    start.ENV_FILE.write_text("original")
    def fail_replace(*args):
        raise OSError("replace failed")
    monkeypatch.setattr(start.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        start.write_env({"PLANNER": "stub"})
    assert start.ENV_FILE.read_text() == "original"
    assert list(start.ENV_FILE.parent.glob(".env.local-*")) == []


def test_atomic_config_and_subprocess_use_exact_raw_values(launcher):
    config = start.planner_config("xai", XAI_API_KEY="fake-$name #quoted ' \" slash\\")
    assert start.launch(config) == 0
    assert launcher[0][1]["env"]["XAI_API_KEY"] == config["XAI_API_KEY"]
    assert start.ENV_FILE.read_text().endswith("\n")
    assert "\\$name" in start.ENV_FILE.read_text()
    if os.name != "nt":
        assert Path(start.ENV_FILE).stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(shutil.which("docker") is None, reason="Compose CLI is not installed")
def test_dotenv_values_roundtrip_through_actual_compose_parser(tmp_path):
    # Config rendering is read-only and needs no running Docker engine.
    value = "fake-$MISSING ${ALSO_MISSING} #hash 'quote' \"double\" back\\slash end\\"
    env_file = tmp_path / "launcher.env"
    env_file.write_text("PROBE=" + start.dotenv_value(value) + "\n", encoding="utf-8")
    compose = tmp_path / "compose.yaml"
    compose.write_text('services:\n  target:\n    image: sealed-target:test\n    environment:\n      PROBE: ${PROBE}\n', encoding="utf-8")
    env = {key: item for key, item in os.environ.items() if key != "PROBE"}
    version = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if version.returncode:
        pytest.skip("Compose CLI plugin is not installed")
    result = subprocess.run(["docker", "compose", "--env-file", str(env_file), "-f", str(compose), "config", "--environment"], capture_output=True, text=True, env=env, check=True)
    # --environment exposes the parsed interpolation value. Serialized Compose
    # config escapes every dollar again so that its output is itself reusable.
    observed = next(line.removeprefix("PROBE=") for line in result.stdout.splitlines() if line.startswith("PROBE="))
    assert observed == value
