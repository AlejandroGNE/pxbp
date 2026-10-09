"""Discover converted solution folders using reported model metadata."""
from __future__ import annotations

import re
from pathlib import Path

import duckdb

from .sources import Source


def discover_sources(root, pattern="*"):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Discovery root must be a directory")
    sources, metadata, used = [], [], set()
    for folder in sorted(root.glob(pattern)):
        if not folder.is_dir() or not list((folder / "fullkeyinfo").glob("*.parquet")):
            continue
        with duckdb.connect() as con:
            models = [r[0] for r in con.execute("SELECT DISTINCT ModelName FROM read_parquet(?) ORDER BY ModelName",
                [str(folder / "fullkeyinfo" / "*.parquet")]).fetchall() if r[0]]
        fallback = re.sub(r"_[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}$", "", folder.name)
        label = models[0] if len(models) == 1 else fallback
        if label in used:
            raise ValueError(f"Duplicate reported model label {label!r}; select one run or label sources manually")
        used.add(label)
        sources.append(Source(label, path=str(folder)))
        metadata.append({"label": label, "models": models, "path": str(folder)})
    if not sources:
        raise ValueError("No converted solution folders matched; check root and pattern")
    return sources, metadata
