"""Immutable word-rule defaults shipped with the application release.

These JSON assets are versioned code/configuration, not mutable runtime state.
PostgreSQL stores operator overrides; the assets are read once at import time so
the full curated vocabulary remains the fallback without ever being rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path


_DIRECTORY = Path(__file__).resolve().parent


def _load(name: str) -> dict:
    return json.loads((_DIRECTORY / name).read_text(encoding="utf-8"))


DANMAKU_FILTERS = _load("danmaku_filters.json")
MEME_STOPWORDS = _load("meme_stopwords.json")["categories"]
MEME_SEED_WORDS = _load("meme_seed_words.json")["words"]
TAG_FILTERS = _load("tag_filters.json")
