"""Which sources run is config, not a hardcoded list in the orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from swarm.sources.arxiv import ArxivSource
from swarm.sources.base import SourceAdapter
from swarm.sources.brave import BraveSource
from swarm.sources.cftc import CftcSource
from swarm.sources.eia import EiaSource
from swarm.sources.federal_register import FederalRegisterSource
from swarm.sources.fred import FredSource
from swarm.sources.gdelt import GdeltSource
from swarm.sources.hn import HackerNewsSource
from swarm.sources.huggingface import HuggingFacePapersSource
from swarm.sources.journals import JournalRssSource
from swarm.sources.openalex import OpenAlexSource
from swarm.sources.reddit import RedditSource
from swarm.sources.regulations import RegulationsGovSource
from swarm.sources.reliefweb import ReliefWebSource
from swarm.sources.sam_gov import SamGovSource
from swarm.sources.wikipedia import WikipediaSource

CONFIG = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"

_CLASSES: dict[str, type[SourceAdapter]] = {
    "hacker_news": HackerNewsSource,
    "reddit": RedditSource,
    "wikipedia": WikipediaSource,
    "brave": BraveSource,
    "federal_register": FederalRegisterSource,
    "arxiv": ArxivSource,
    "huggingface": HuggingFacePapersSource,
    "journals": JournalRssSource,
    "openalex": OpenAlexSource,
    "regulations_gov": RegulationsGovSource,
    "sam_gov": SamGovSource,
    "gdelt": GdeltSource,
    "reliefweb": ReliefWebSource,
    "eia": EiaSource,
    "fred": FredSource,
    "cftc": CftcSource,
}

# Sources that cannot fetch without a key. Reddit can still use the public JSON
# path, so a missing Reddit key is not "needs key".
_KEY_ATTR = {
    "brave": "brave_api_key",
    "openalex": "openalex_api_key",
    "regulations_gov": "regulations_gov_api_key",
    "sam_gov": "sam_gov_api_key",
    "eia": "eia_api_key",
    "fred": "fred_api_key",
}


def load_source_config() -> list[dict[str, Any]]:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    return list(raw.get("sources") or [])


def build_sources() -> list[SourceAdapter]:
    sources: list[SourceAdapter] = []
    for row in load_source_config():
        source_id = str(row.get("id") or "")
        cls = _CLASSES.get(source_id)
        if cls is None:
            continue
        adapter = cls()
        adapter._config_enabled = bool(row.get("enabled", True))  # type: ignore[attr-defined]
        adapter._key_attr = _KEY_ATTR.get(source_id, "")  # type: ignore[attr-defined]
        sources.append(adapter)
    return sources


def missing_keys(sources: list[SourceAdapter] | None = None) -> list[str]:
    rows = sources if sources is not None else build_sources()
    return [src.name for src in rows if src.availability() == "needs key"]
