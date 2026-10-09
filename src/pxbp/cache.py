"""Optional disk cache of complete source queries, stored as bounded Parquet batches."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

import duckdb
import pandas as pd

from .sources import Batch, Cancelled, reader_for


def cache_key(source, selection):
    identity = asdict(source)
    if source.path:
        root = Path(source.path).resolve()
        # Invalidate when any query input changes. No dataset content is copied.
        identity["files"] = [(str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*.parquet"))]
    return hashlib.sha256(json.dumps({"format": 1, "source": identity,
        "query": selection.query}, sort_keys=True).encode()).hexdigest()


def query_cached(sources, selection, cache_dir=None, cancel=None, progress=None, *, refresh=False):
    cancel = cancel or threading.Event()
    remaining = selection.max_rows
    root = Path(cache_dir).expanduser().resolve() if cache_dir else None
    if root:
        root.mkdir(parents=True, exist_ok=True)
    for source in sources:
        if cancel.is_set():
            raise Cancelled("Query cancelled")
        key = cache_key(source, selection) if root else None
        manifest_path = root / (key + ".json") if root else None
        if manifest_path and manifest_path.is_file() and not refresh:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if Path(manifest["folder"]).name != manifest["folder"]:
                raise ValueError("Invalid cache manifest")
            destination = root / manifest["folder"]
            if manifest["rows"] > remaining:
                raise ValueError("Row limit exceeded by cached results; increase max_rows or narrow the query")
            if progress:
                progress(source, "cache")
            with duckdb.connect() as con:
                for name in manifest["parts"]:
                    if Path(name).name != name:
                        raise ValueError("Invalid cache manifest")
                    cursor = con.execute("SELECT * FROM read_parquet(?)", [str(destination / name)])
                    columns = [c[0] for c in cursor.description]
                    while rows := cursor.fetchmany(selection.batch_size):
                        if cancel.is_set():
                            raise Cancelled("Query cancelled")
                        frame = pd.DataFrame(rows, columns=columns)
                        remaining -= len(frame)
                        yield Batch(source, frame)
            continue
        if progress:
            progress(source, "query")
        temporary = root / ("pending-" + uuid.uuid4().hex) if root else None
        if temporary:
            temporary.mkdir()
        parts, count = [], 0
        try:
            for frame in reader_for(source, cancel, selection.timeout).rows(selection, remaining):
                if temporary:
                    name = f"part-{len(parts):06d}.parquet"
                    with duckdb.connect() as con:
                        con.register("batch", frame)
                        con.execute("COPY batch TO ? (FORMAT PARQUET)", [str(temporary / name)])
                    parts.append(name)
                count += len(frame)
                remaining -= len(frame)
                yield Batch(source, frame)
            if cancel.is_set():
                raise Cancelled("Query cancelled")
            if temporary:
                # Immutable generations let simultaneous readers finish safely.
                destination = root / (key + "-" + uuid.uuid4().hex)
                os.rename(temporary, destination)
                index = root / ("index-" + uuid.uuid4().hex + ".json")
                index.write_text(json.dumps({"rows": count, "parts": parts, "folder": destination.name}), encoding="utf-8")
                os.replace(index, manifest_path)
        finally:
            if temporary and temporary.exists():
                temporary.resolve().relative_to(root)
                shutil.rmtree(temporary)
