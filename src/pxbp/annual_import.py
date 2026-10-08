"""Import native annual build summaries from a solution ZIP into queryable Parquet."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd


def import_annual_zip(archive, output):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new import output folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped, tempfile.TemporaryDirectory(dir=output.parent, prefix="annual-import-") as temp:
        root = Path(temp)
        con = duckdb.connect(str(root / "staging.duckdb"))
        try:
            con.execute("BEGIN")
            con.execute("CREATE TABLE vals (SeriesId BIGINT, PeriodId INTEGER, Value DOUBLE)")
            con.execute("CREATE TABLE keys (SeriesId BIGINT, ParentClassName VARCHAR, CollectionName VARCHAR, ChildClassName VARCHAR, ChildObjectName VARCHAR, PropertyName VARCHAR, PhaseName VARCHAR, PeriodTypeName VARCHAR, TimesliceName VARCHAR, SampleName VARCHAR, ModelName VARCHAR, UnitValue VARCHAR, BandId INTEGER)")
            matcher = re.compile(r"Model (.+) (Generator|Battery) Units Built\.csv$", re.IGNORECASE)
            members = [(name, matcher.fullmatch(Path(name).name)) for name in zipped.namelist()]
            members = [(name, match) for name, match in members if match]
            if not members or len({match[1] for _, match in members}) != 1:
                raise ValueError("ZIP needs annual Generator/Battery Units Built summaries for one model")
            counts, years, seen, identities = {}, set(), set(), {}
            for name, match in members:
                model, asset_class = match[1], match[2].title()
                collection = "Generators" if asset_class == "Generator" else "Batteries"
                count, batch = 0, []
                with zipped.open(name) as binary, io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if not reader.fieldnames or not {"Name", "Year", "Value"} <= set(reader.fieldnames):
                        raise ValueError(f"Unexpected annual summary columns: {name}")
                    for item in reader:
                        year = int(item["Year"])
                        datetime(year, 1, 1)  # Validate the year before writing.
                        if not item["Name"] or any(item.get(k) not in (None, "", "1") for k in ("Month", "Day", "Period")):
                            raise ValueError("Expected one annual row per asset/year; found subannual summary")
                        identity = (collection, item["Name"])
                        unique = (*identity, year)
                        if unique in seen:
                            raise ValueError(f"Duplicate native annual asset/year: {unique}")
                        seen.add(unique); years.add(year)
                        if identity not in identities:
                            series_id = len(identities) + 1
                            identities[identity] = series_id
                            con.execute("INSERT INTO keys VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [series_id, "System", collection,
                                asset_class, item["Name"], "Units Built", "NativeAnnual", "Year", "All Periods", "Native summary", model, "-", 1])
                        batch.append((identities[identity], year, float(item["Value"])))
                        count += 1
                        if len(batch) == 5000:
                            annual_values = pd.DataFrame(batch, columns=["SeriesId", "PeriodId", "Value"])
                            con.execute("INSERT INTO vals SELECT * FROM annual_values")
                            batch = []
                    if batch:
                        annual_values = pd.DataFrame(batch, columns=["SeriesId", "PeriodId", "Value"])
                        con.execute("INSERT INTO vals SELECT * FROM annual_values")
                if not count:
                    raise ValueError(f"Empty annual summary: {name}")
                counts[name] = count
            if con.execute("SELECT count(*) FROM vals WHERE Value IS NULL OR NOT isfinite(Value) OR Value < -1e-8").fetchone()[0]:
                raise ValueError("Native annual builds contain nonfinite or negative values")
            con.execute("CREATE TABLE periods AS SELECT DISTINCT PeriodId, make_timestamp(PeriodId,1,1,0,0,0) AS StartDate, make_timestamp(PeriodId+1,1,1,0,0,0) AS EndDate FROM vals")
            for table, folder in (("keys", "fullkeyinfo"), ("vals", "data"), ("periods", "period")):
                (root / folder).mkdir()
                con.execute(f"COPY {table} TO ? (FORMAT PARQUET)", [str(root / folder / "part.parquet")])
        finally:
            con.close()
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                digest.update(chunk)
        checksum = digest.hexdigest()
        provenance = {"archive": archive.name, "archive_sha256": checksum, "members": counts,
                      "years": sorted(years), "scope": "Native annual Units Built summaries only",
                      "phase": "NativeAnnual", "sample": "Native summary"}
        output.mkdir()
        for folder in ("fullkeyinfo", "data", "period"):
            (root / folder).rename(output / folder)
        (output / "import-provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return output
