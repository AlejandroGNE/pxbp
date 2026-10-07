"""Create two small synthetic Parquet solutions for trying pxbp without private data."""
import argparse
import json
from pathlib import Path

import duckdb


def create_demo(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Choose a new output directory: {destination}")
    destination.mkdir(parents=True)
    for label, scale in (("baseline", 1.0), ("alternative", 1.15)):
        root = destination / label
        for folder in ("fullkeyinfo", "data", "period"):
            (root / folder).mkdir(parents=True)
        con = duckdb.connect()
        try:
            con.execute("CREATE TABLE keys (SeriesId INTEGER, ParentClassName VARCHAR, CollectionName VARCHAR, ChildClassName VARCHAR, ChildObjectName VARCHAR, ChildObjectCategoryName VARCHAR, PropertyName VARCHAR, PhaseName VARCHAR, PeriodTypeName VARCHAR, TimesliceName VARCHAR, SampleName VARCHAR, ModelName VARCHAR, UnitValue VARCHAR, BandId INTEGER)")
            con.execute("INSERT INTO keys VALUES (1,'System','Generators','Generator','Gas plant','Gas','Generation','ST','Interval','All Periods','Mean','Demo','MWh',1), (2,'System','Generators','Generator','Wind farm','Wind','Generation','ST','Interval','All Periods','Mean','Demo','MWh',1)")
            con.execute("CREATE TABLE periods AS SELECT i::INTEGER AS PeriodId, TIMESTAMP '2024-01-01' + i * INTERVAL '1 hour' AS StartDate, TIMESTAMP '2024-01-01' + (i+1) * INTERVAL '1 hour' AS EndDate FROM range(48) t(i)")
            con.execute("CREATE TABLE vals AS SELECT SeriesId, PeriodId, ? * CASE WHEN SeriesId=1 THEN 50 + 10*sin(PeriodId*pi()/12) ELSE 20 + 8*cos(PeriodId*pi()/8) END AS Value FROM keys CROSS JOIN periods", [scale])
            for table, folder in (("keys", "fullkeyinfo"), ("vals", "data"), ("periods", "period")):
                con.execute(f"COPY {table} TO ? (FORMAT PARQUET)", [str(root / folder / "part.parquet")])
        finally:
            con.close()
    config = destination / "sources.json"
    config.write_text(json.dumps({"sources": [{"label": "Demo baseline", "path": "baseline"},
                                              {"label": "Demo alternative", "path": "alternative"}]}, indent=2), encoding="utf-8")
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="work/demo-parquet")
    args = parser.parse_args()
    print(create_demo(args.output))
