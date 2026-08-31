from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache
def verticals() -> list[dict[str, Any]]:
    rows = _load_yaml("verticals.yaml").get("verticals") or []
    return [v for v in rows if v.get("enabled", True)]


@lru_cache
def lenses() -> list[dict[str, Any]]:
    rows = _load_yaml("lenses.yaml").get("lenses") or []
    return [ln for ln in rows if ln.get("enabled", True)]


def vertical_by_id(vid: str) -> dict[str, Any] | None:
    for v in verticals():
        if v["id"] == vid:
            return v
    return None


def lens_by_id(lid: str) -> dict[str, Any] | None:
    for ln in lenses():
        if ln["id"] == lid:
            return ln
    return None
