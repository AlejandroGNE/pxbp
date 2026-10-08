"""Create two synthetic annual build solutions and their report specification."""
import argparse
import json
from pathlib import Path

import duckdb


def create_demo(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Choose a new directory: {destination}")
    destination.mkdir(parents=True)
    for scenario, scale in (("case-a", 1), ("case-b", 1.25)):
        root = destination / scenario
        con = duckdb.connect()
        con.execute("CREATE TABLE keys (SeriesId INTEGER, ParentClassName VARCHAR, CollectionName VARCHAR, ChildClassName VARCHAR, ChildObjectName VARCHAR, ChildObjectCategoryName VARCHAR, PropertyName VARCHAR, PhaseName VARCHAR, PeriodTypeName VARCHAR, TimesliceName VARCHAR, SampleName VARCHAR, ModelName VARCHAR, UnitValue VARCHAR, BandId INTEGER)")
        con.execute("INSERT INTO keys VALUES (1,'System','Generators','Generator','Solar A','Expansion','Units Built','LT','Year','All Periods','Mean','Demo','-',1), (2,'System','Generators','Generator','Wind A','Expansion','Units Built','LT','Year','All Periods','Mean','Demo','-',1), (3,'System','Batteries','Battery','Battery A','Expansion','Units Built','LT','Year','All Periods','Mean','Demo','-',1), (4,'System','Generators','Generator','Flowgate proxy','Infrastructure','Units Built','LT','Year','All Periods','Mean','Demo','-',1)")
        con.execute("CREATE TABLE periods AS SELECT i::INTEGER AS PeriodId, make_timestamp(2030+i,1,1,0,0,0) AS StartDate, make_timestamp(2031+i,1,1,0,0,0) AS EndDate FROM range(3) t(i)")
        con.execute("CREATE TABLE vals AS SELECT SeriesId, PeriodId, ? * CASE WHEN SeriesId=1 THEN 2+PeriodId WHEN SeriesId=2 THEN 1.5 WHEN SeriesId=3 THEN 0.5 ELSE 10 END AS Value FROM keys CROSS JOIN periods", [scale])
        for table, folder in (("keys", "fullkeyinfo"), ("periods", "period"), ("vals", "data")):
            (root / folder).mkdir(parents=True)
            con.execute(f"COPY {table} TO ? (FORMAT PARQUET)", [str(root / folder / "part.parquet")])
        con.close()
    (destination / "sources.json").write_text(json.dumps({"sources": [{"label": "Case A", "path": "case-a"}, {"label": "Case B", "path": "case-b"}]}, indent=2), encoding="utf-8")
    query = {"properties": "Units Built", "phase": "LTPlan", "period": "Year", "timeslice": "All Periods", "sample": "Mean", "model": "Demo"}
    spec = {"title": "New capacity by region", "years": [2030, 2031, 2032],
            "queries": [{"collection": "SystemGenerators", **query}, {"collection": "SystemBatteries", **query}],
            "notes": "Synthetic demonstration. Battery ratings describe power in MW.",
            "assets": [
                {"collection": "SystemGenerators", "object_name": "Solar A", "region": "Region A", "technology": "UPV", "capacity_mw": 200},
                {"collection": "SystemGenerators", "object_name": "Wind A", "region": "Region B", "technology": "Onshore Wind", "capacity_mw": 150},
                {"collection": "SystemBatteries", "object_name": "Battery A", "region": "Region A", "technology": "Battery", "capacity_mw": 100},
                {"collection": "SystemGenerators", "object_name": "Flowgate proxy", "exclude_reason": "Infrastructure proxy; does not represent generation"},
            ]}
    (destination / "capacity-spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="work/demo-capacity")
    print(create_demo(parser.parse_args().output))
