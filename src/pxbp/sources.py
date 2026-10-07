"""Cloud and local Parquet adapters sharing bounded, normalized result batches."""
from __future__ import annotations

import csv
import json
import math
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd
from plexos_query.cloud_cli import CloudSolution
from plexos_query import Solution


class Cancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    label: str
    solution_id: str | None = None
    path: str | None = None

    def __post_init__(self):
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Each source needs a nonempty scenario label")
        if bool(self.solution_id) == bool(self.path):
            raise ValueError("Each source needs exactly one of solution_id or path")
        if self.solution_id:
            if not isinstance(self.solution_id, str):
                raise ValueError("solution_id must be a UUID string")
            UUID(self.solution_id)
        elif not isinstance(self.path, (str, Path)):
            raise ValueError("path must name a converted solution folder")

    @property
    def kind(self):
        return "cloud" if self.solution_id else "parquet"


QUERY_FIELDS = {"collection", "properties", "phase", "period", "parent", "child",
                "category", "timeslice", "sample", "model", "date_from", "date_to",
                "aggregate_by", "aggregate_type", "filter"}


@dataclass(frozen=True)
class Selection:
    query: dict
    batch_size: int = 5000
    max_rows: int = 100000
    window_days: int = 0
    timeout: float = 180

    def __post_init__(self):
        if not isinstance(self.query, dict) or any(not isinstance(key, str) for key in self.query):
            raise ValueError("Selection must be a JSON object with named query fields")
        unknown = set(self.query) - QUERY_FIELDS
        if unknown:
            raise ValueError("Unknown query fields: " + ", ".join(sorted(unknown)))
        if not self.query.get("collection") or not self.query.get("properties"):
            raise ValueError("Choose a collection and at least one property")
        if (not isinstance(self.batch_size, int) or not isinstance(self.max_rows, int)
                or not 1 <= self.batch_size <= 100000 or not 1 <= self.max_rows <= 1000000):
            raise ValueError("batch_size must be 1–100000; max_rows must be 1–1000000")
        if not isinstance(self.timeout, (int, float)) or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        if not isinstance(self.window_days, int) or not 0 <= self.window_days <= 366:
            raise ValueError("window_days must be 0–366")
        start = self.query.get("date_from")
        end = self.query.get("date_to")
        if any(value is not None and not isinstance(value, str) for value in (start, end)):
            raise ValueError("Date bounds must be ISO timestamp strings")
        if start:
            datetime.fromisoformat(start)
        if end:
            datetime.fromisoformat(end)
        if start and end:
            first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if (first.tzinfo is None) != (last.tzinfo is None):
                raise ValueError("Use consistent timezone notation in date bounds")
            if first > last:
                raise ValueError("date_from must be no later than date_to")
        if self.window_days:
            if not start or not end:
                raise ValueError("Windowed cloud queries need date_from and date_to")
            if self.query.get("aggregate_by") == "period":
                raise ValueError("Period aggregation cannot be split into date windows")

    def windows(self):
        if not self.window_days:
            yield None
            return
        start = datetime.fromisoformat(self.query["date_from"])
        end = datetime.fromisoformat(self.query["date_to"])
        while start <= end:
            stop = start + timedelta(days=self.window_days)
            yield start, stop
            start = stop


def load_sources(path: str | Path) -> list[Source]:
    config_path = Path(path).expanduser().resolve()
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or set(data) != {"sources"}:
        raise ValueError('Configuration must contain only a "sources" array')
    if not isinstance(data["sources"], list):
        raise ValueError('"sources" must be a JSON array')
    result = []
    for item in data["sources"]:
        if not isinstance(item, dict) or set(item) not in ({"label", "solution_id"}, {"label", "path"}):
            raise ValueError("Sources need label and exactly one of solution_id or path")
        if "path" in item:
            if not isinstance(item["path"], str) or not item["path"].strip():
                raise ValueError("Source path must be a nonempty string")
            local = Path(item["path"]).expanduser()
            item["path"] = str((config_path.parent / local).resolve())
        result.append(Source(**item))
    if not result or len({s.label for s in result}) != len(result):
        raise ValueError("Use at least one source and unique scenario labels")
    return result


def run_cli(command, cancel: threading.Event, timeout: float):
    """Use files for diagnostics so a full stderr pipe cannot deadlock the worker."""
    if cancel.is_set():
        raise Cancelled("Query cancelled")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancel.wait(0.1):
                    raise Cancelled("Query cancelled")
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"Cloud CLI exceeded {timeout:g} seconds")
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read().decode("utf-8-sig", errors="replace")
            errors = stderr.read().decode("utf-8-sig", errors="replace")
            if process.returncode:
                raise RuntimeError(errors.strip() or output.strip() or
                                   f"Cloud CLI failed (exit {process.returncode}); check login and solution readiness")
            return output
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


class ManagedCloud(CloudSolution):
    def __init__(self, source, cancel, timeout):
        super().__init__(source.solution_id)
        self.cancel, self.timeout = cancel, timeout

    def _metadata(self, sql):
        output = run_cli([self.executable, "solution", "sql", "--solution-id",
                          self.solution_id, "--sql", sql, "--format", "json", "--quiet"],
                         self.cancel, self.timeout)
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Cloud CLI returned invalid JSON metadata") from exc


COLUMNS = ["scenario", "solution_id", "source_path", "source_kind", "collection_name", "class_name", "property_name",
           "phase_name", "period_type_name", "object_name", "category_name", "unit",
           "timeslice_name", "sample_name", "model_name", "band_id", "start_date", "end_date", "value"]


def normalize(rows, source):
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    if not {"start_date", "value"}.issubset(frame.columns):
        raise ValueError("Query result must include start_date and value")
    frame["scenario"] = source.label
    frame["solution_id"] = source.solution_id or ""
    frame["source_path"] = source.path or ""
    frame["source_kind"] = source.kind
    for name in COLUMNS:
        if name not in frame:
            frame[name] = ""
    for name in ("start_date", "end_date"):
        frame[name] = pd.to_datetime(frame[name], format="mixed", errors="raise")
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if frame["start_date"].isna().any() or not frame["value"].map(math.isfinite).all():
        raise ValueError("Result contains missing dates or non-finite values")
    for name in set(COLUMNS) - {"start_date", "end_date", "value"}:
        frame[name] = frame[name].fillna("").astype(str)
    return frame[COLUMNS]


@dataclass
class Batch:
    source: Source
    frame: pd.DataFrame


class CloudReader:
    def __init__(self, source, cancel, timeout):
        self.source, self.cancel, self.timeout = source, cancel, timeout
        self.cloud = ManagedCloud(source, cancel, timeout)

    def explore(self, collection):
        return self.cloud.explore(collection)

    def rows(self, selection, remaining):
        sql = self.cloud.build_sql(**selection.query)
        if len(sql.encode("utf-8")) >= 1000000:
            raise ValueError("Generated SQL exceeds the Cloud CLI 1 MB limit")
        for window in selection.windows():
            if self.cancel.is_set():
                raise Cancelled("Query cancelled")
            window_sql = sql
            if window:
                start, stop = window
                window_sql = (f"SELECT * FROM ({sql}) q WHERE start_date >= TIMESTAMP '{start.isoformat()}' "
                              f"AND start_date < TIMESTAMP '{stop.isoformat()}'")
            # One extra row detects truncation instead of silently publishing incomplete totals.
            limited = f"SELECT * FROM ({window_sql}) q LIMIT {remaining + 1}"
            with tempfile.TemporaryDirectory(prefix="pxbp-") as directory:
                root = Path(directory)
                (root / "query.sql").write_text(limited, encoding="utf-8")
                target = root / "result.csv"
                run_cli([self.cloud.executable, "solution", "sql", "--solution-id",
                         self.source.solution_id, "--sql-file", str(root / "query.sql"),
                         "--output-file", str(target), "--format", "csv"],
                        self.cancel, self.timeout)
                if not target.is_file():
                    raise RuntimeError("Cloud CLI did not produce a result file")
                with target.open(encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if not reader.fieldnames or not {"start_date", "value"}.issubset(reader.fieldnames):
                        raise ValueError("Cloud CLI returned an unexpected CSV schema")
                    batch = []
                    for row in reader:
                        if self.cancel.is_set():
                            raise Cancelled("Query cancelled")
                        remaining -= 1
                        if remaining < 0:
                            raise ValueError("Row limit exceeded; narrow the query or increase max_rows. Results are incomplete")
                        batch.append(row)
                        if len(batch) == selection.batch_size:
                            yield normalize(batch, self.source)
                            batch = []
                    if batch:
                        yield normalize(batch, self.source)


class LocalReader:
    """Use the pinned pxq SQL builder and DuckDB fetchmany; no CSV is created."""
    def __init__(self, source, cancel, timeout):
        self.source, self.cancel, self.timeout = source, cancel, timeout

    def explore(self, collection):
        if self.cancel.is_set():
            raise Cancelled("Query cancelled")
        with Solution(self.source.path) as solution:
            return solution.explore(collection=collection)

    def rows(self, selection, remaining):
        if self.cancel.is_set():
            raise Cancelled("Query cancelled")
        with Solution(self.source.path) as solution:
            con = solution._ready()
            done, timed_out = threading.Event(), threading.Event()

            def watch():
                started = time.monotonic()
                while not done.wait(0.05):
                    if self.cancel.is_set():
                        con.interrupt()
                        return
                    if time.monotonic() - started > self.timeout:
                        timed_out.set()
                        con.interrupt()
                        return

            monitor = threading.Thread(target=watch, daemon=True, name="pxbp-duckdb-cancel")
            monitor.start()
            try:
                # This dependency-private boundary is pinned and covered by adapter/parity tests.
                sql, params = solution._query_sql(**selection.query)
                sql = sql.removesuffix(" ORDER BY p.StartDate, f.SeriesId")
                result = con.execute(f"SELECT * FROM ({sql}) q LIMIT ?", params + [remaining + 1])
                names = [column[0] for column in result.description]
                while True:
                    if self.cancel.is_set():
                        raise Cancelled("Query cancelled")
                    if timed_out.is_set():
                        raise TimeoutError(f"Local query exceeded {self.timeout:g} seconds")
                    rows = result.fetchmany(min(selection.batch_size, remaining + 1))
                    if not rows:
                        break
                    if len(rows) > remaining:
                        raise ValueError("Row limit exceeded; narrow the query or increase max_rows. Results are incomplete")
                    remaining -= len(rows)
                    yield normalize([dict(zip(names, row)) for row in rows], self.source)
            except Exception as exc:
                if self.cancel.is_set():
                    raise Cancelled("Query cancelled") from exc
                if timed_out.is_set():
                    raise TimeoutError(f"Local query exceeded {self.timeout:g} seconds") from exc
                raise
            finally:
                done.set()
                monitor.join()


def reader_for(source, cancel, timeout):
    return CloudReader(source, cancel, timeout) if source.kind == "cloud" else LocalReader(source, cancel, timeout)


def stream_query(sources, selection, cancel=None):
    cancel = cancel or threading.Event()
    remaining = selection.max_rows
    for source in sources:
        reader = reader_for(source, cancel, selection.timeout)
        for frame in reader.rows(selection, remaining):
            remaining -= len(frame)
            yield Batch(source, frame)

