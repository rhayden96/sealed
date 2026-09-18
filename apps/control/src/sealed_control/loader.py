from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_catalog(path: str | Path) -> dict[str, Any]:
    return load_yaml(path)


def load_policy(path: str | Path) -> dict[str, Any]:
    return load_yaml(path)


def experiments_by_id(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in catalog.get("experiments", [])}


def load_fixture_seals(path: str | Path) -> list[dict[str, Any]]:
    directory = Path(path)
    if not directory.is_dir():
        return []
    seals: list[dict[str, Any]] = []
    for file in sorted(directory.glob("*.json")):
        seals.append(json.loads(file.read_text(encoding="utf-8")))
    return seals
