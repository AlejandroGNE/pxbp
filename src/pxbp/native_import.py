"""Select annual properties from a native ZIP without a full solution conversion."""
from __future__ import annotations

import gc
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

COLLECTIONS = {"SystemGenerators": (1, "Generators", "Generator"),
               "SystemBatteries": (81, "Batteries", "Battery"),
               "SystemZones": (252, "Zones", "Zone"),
               "SystemLines": (321, "Lines", "Line"),
               "SystemConstraints": (724, "Constraints", "Constraint"),
               "SystemInterfaces": (352, "Interfaces", "Interface")}


def import_native_annual(archive, output, spec, api_path, *, progress=print):
    """Requires pythonnet and a compatible installed PLEXOS API; queries one year at a time."""
    archive, output, api_path = map(lambda p: Path(p).resolve(), (archive, output, api_path))
    if output.exists():
        raise ValueError("Choose a new import output folder")
    if not (api_path / "PLEXOS_NET.Core.dll").is_file():
        raise ValueError("api_path must contain PLEXOS_NET.Core.dll")
    years = spec.get("years", [])
    if not years or any(type(y) is not int or not 1 <= y < 9999 for y in years) or len(set(years)) != len(years):
        raise ValueError("Specify distinct calendar years")
    queries = spec.get("collections", {})
    if not queries or set(queries) - COLLECTIONS.keys():
        raise ValueError("Choose supported native annual collections")
    for properties in queries.values():
        if not isinstance(properties, list) or not properties or any(not isinstance(p, str) or not p for p in properties):
            raise ValueError("Each collection needs a nonempty property name array")
    sys.path.append(str(api_path))
    import clr
    for assembly in ("PLEXOS_NET.Core", "EEUTILITY", "EnergyExemplar.PLEXOS.Utility"):
        clr.AddReference(assembly)
    from PLEXOS_NET.Core import Solution
    from EEUTILITY.Enums import SimulationPhaseEnum, AggregationTypeEnum, OperationTypeEnum
    from EnergyExemplar.PLEXOS.Utility.Enums import PeriodEnum, SeriesTypeEnum
    from System import DateTime, Enum

    solution = Solution()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="native-annual-") as staging:
        root = Path(staging)
        con = duckdb.connect(str(root / "staging.duckdb"))
        con.execute("CREATE TABLE vals (SeriesId BIGINT, PeriodId INTEGER, Value DOUBLE)")
        key_columns = ["SeriesId", "ParentClassName", "CollectionName", "ChildClassName", "ChildObjectName",
                       "PropertyName", "PhaseName", "PeriodTypeName", "TimesliceName", "SampleName", "ModelName", "UnitValue", "BandId", "ChildObjectCategoryName"]
        con.execute("CREATE TABLE keys (SeriesId BIGINT, ParentClassName VARCHAR, CollectionName VARCHAR, ChildClassName VARCHAR, ChildObjectName VARCHAR, PropertyName VARCHAR, PhaseName VARCHAR, PeriodTypeName VARCHAR, TimesliceName VARCHAR, SampleName VARCHAR, ModelName VARCHAR, UnitValue VARCHAR, BandId INTEGER, ChildObjectCategoryName VARCHAR)")
        identities, coverage = {}, []
        try:
            progress("Opening native solution", flush=True)
            solution.Connection(str(archive))
            for collection, properties in queries.items():
                _, plural, child_class = COLLECTIONS[collection]
                # Collection IDs can change between model/API versions.
                try:
                    collection_id = int(solution.CollectionName2Id("System", child_class, plural))
                except Exception as exc:
                    if "cannot be found in the input database" not in str(exc):
                        raise
                    coverage.extend({"collection": collection, "property": p, "status": "collection not present"} for p in properties)
                    continue
                available = {}
                for prop in properties:
                    try:
                        available[prop] = int(solution.PropertyName2EnumId(collection_id, prop, False))
                    except Exception as exc:
                        # Only an explicit unavailable property is an expected coverage gap.
                        if "cannot be found in the output database" not in str(exc):
                            raise
                        coverage.append({"collection": collection, "property": prop, "status": "not reported"})
                if not available:
                    continue
                pending, window = sorted(years), 1
                while pending:
                    selected_years = pending[:window]
                    # Never bridge an omitted reporting year.
                    while selected_years[-1] - selected_years[0] + 1 != len(selected_years):
                        selected_years.pop()
                    year, last_year = selected_years[0], selected_years[-1]
                    progress(f"{collection}: {year}-{last_year} ({len(available)} properties)", flush=True)
                    result = solution.QueryToList(SimulationPhaseEnum.LTPlan, collection_id, "", "",
                        PeriodEnum.FiscalYear, SeriesTypeEnum.Values, ",".join(map(str, available.values())),
                        DateTime(year, 1, 1), DateTime(last_year, 12, 31, 23, 59, 59), "", "", "",
                        Enum.ToObject(AggregationTypeEnum, 0), "", "", OperationTypeEnum.SUM)
                    count = 0 if result is None else int(result.Count)
                    if count > spec.get("max_rows_per_query", 250000):
                        raise ValueError("Native annual query exceeded row limit; select fewer properties")
                    values, new_keys, seen, counts = [], [], set(), {}
                    if result is not None:
                        for row in result:
                            row_year = int(row._date.Year)
                            if row_year not in selected_years:
                                raise ValueError("Native fiscal year does not match the selected calendar year")
                            value = float(row.value)
                            if not math.isfinite(value):
                                raise ValueError("Native query returned a nonfinite value")
                            identity = (plural, str(row.child_name), str(row.property_name), str(row.phase_name),
                                str(row.timeslice_name), str(row.sample_name), str(row.model_name), str(row.unit_name), int(row.band_id))
                            unique = (*identity, row_year)
                            if unique in seen:
                                raise ValueError("Duplicate native series/year; annual query must retain one row per dimension")
                            seen.add(unique)
                            if identity not in identities:
                                series_id = len(identities) + 1
                                identities[identity] = series_id
                                new_keys.append((series_id, "System", plural, child_class, str(row.child_name), str(row.property_name),
                                    "LTPlan", "Year", str(row.timeslice_name), str(row.sample_name), str(row.model_name),
                                    str(row.unit_name), int(row.band_id), str(row.category_name)))
                            values.append((identities[identity], row_year, value))
                            counts[(str(row.property_name), row_year)] = counts.get((str(row.property_name), row_year), 0) + 1
                    if new_keys:
                        keys_frame = pd.DataFrame(new_keys, columns=key_columns)
                        con.execute("INSERT INTO keys SELECT * FROM keys_frame")
                    if values:
                        values_frame = pd.DataFrame(values, columns=["SeriesId", "PeriodId", "Value"])
                        con.execute("INSERT INTO vals SELECT * FROM values_frame")
                    coverage.extend({"collection": collection, "property": prop, "year": y,
                                     "rows": counts.get((prop, y), 0), "status": "reported" if counts.get((prop, y)) else "no annual rows"}
                                    for prop in available for y in selected_years)
                    progress(f"Read {count} rows", flush=True)
                    pending = pending[len(selected_years):]
                    rows_per_year = max(count / len(selected_years), 1)
                    window = max(1, min(15, int(spec.get("max_rows_per_query", 250000) * .8 / rows_per_year)))
                    del result, values, new_keys
                    gc.collect()
            con.execute("CREATE TABLE periods AS SELECT DISTINCT PeriodId, make_timestamp(PeriodId,1,1,0,0,0) StartDate, make_timestamp(PeriodId+1,1,1,0,0,0) EndDate FROM vals")
            total_rows = con.execute("SELECT count(*) FROM vals").fetchone()[0]
            if not total_rows:
                progress("No selected annual properties reported; recording coverage only", flush=True)
            for table, folder in (("keys", "fullkeyinfo"), ("vals", "data"), ("periods", "period")):
                (root / folder).mkdir()
                con.execute(f"COPY {table} TO ? (FORMAT PARQUET)", [str(root / folder / "part.parquet")])
        finally:
            solution.Close()
            con.close()
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                digest.update(chunk)
        provenance = {"archive": archive.name, "archive_sha256": digest.hexdigest(), "specification": spec,
                      "scope": "Selected native LT Plan FiscalYear properties; no CSV intermediates",
                      "api_path": str(api_path), "coverage": coverage, "rows": total_rows,
                      "calendar": "Native annual row labels verified against selected calendar years"}
        output.mkdir()
        for folder in ("fullkeyinfo", "data", "period"):
            (root / folder).rename(output / folder)
        (output / "import-provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return output
