"""Cloud query adapter; temporary CSV is the Cloud CLI transport, not an export workflow."""
from __future__ import annotations

import csv
import json
import math
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd
from plexos_query.cloud_cli import CloudSolution


class Cancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    label: str
    solution_id: str

    def __post_init__(self):
        if not self.label.strip():
            raise ValueError("Each source needs a nonempty scenario label")
        UUID(self.solution_id)


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
        unknown = set(self.query) - QUERY_FIELDS
        if unknown:
            raise ValueError("Unknown query fields: " + ", ".join(sorted(unknown)))
        if not self.query.get("collection") or not self.query.get("properties"):
            raise ValueError("Choose a collection and at least one property")
        if not 1 <= self.batch_size <= 100000 or not 1 <= self.max_rows <= 1000000:
            raise ValueError("batch_size must be 1–100000; max_rows must be 1–1000000")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        if not 0 <= self.window_days <= 366:
            raise ValueError("window_days must be 0–366")
        start = self.query.get("date_from")
        end = self.query.get("date_to")
        if start:
            datetime.fromisoformat(start)
        if end:
            datetime.fromisoformat(end)
        if start and end and datetime.fromisoformat(start) > datetime.fromisoformat(end):
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
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or set(data) != {"sources"}:
        raise ValueError('Configuration must contain only a "sources" array')
    result = []
    for item in data["sources"]:
        if set(item) != {"label", "solution_id"}:
            raise ValueError("Cloud sources need label and solution_id")
        result.append(Source(**item))
    if not result or len({s.label for s in result}) != len(result):
        raise ValueError("Use at least one source and unique scenario labels")
    return result


def run_cli(command, cancel: threading.Event, timeout: float):
    """Use files for diagnostics so a full stderr pipe cannot deadlock the worker."""
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


COLUMNS = ["scenario", "solution_id", "collection_name", "class_name", "property_name",
           "phase_name", "period_type_name", "object_name", "category_name", "unit",
           "timeslice_name", "sample_name", "model_name", "band_id", "start_date", "end_date", "value"]


def normalize(rows, source):
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    if not {"start_date", "value"}.issubset(frame.columns):
        raise ValueError("Query result must include start_date and value")
    frame["scenario"] = source.label
    frame["solution_id"] = source.solution_id
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
                         "--output-file", str(target), "--format", "csv", "--quiet"],
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


def stream_query(sources, selection, cancel=None):
    cancel = cancel or threading.Event()
    remaining = selection.max_rows
    for source in sources:
        reader = CloudReader(source, cancel, selection.timeout)
        for frame in reader.rows(selection, remaining):
            remaining -= len(frame)
            yield Batch(source, frame)

