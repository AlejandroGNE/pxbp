"""Create a synthetic multi-solution workspace with known signed differences."""
import argparse
from pathlib import Path
import json

import duckdb

from pxbp.sources import Source
from pxbp.workspace import make_workspace, PRESETS


def create_demo(destination, cases=36):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new demo directory")
    if not 2 <= cases <= 100:
        raise ValueError("Choose 2–100 demo solutions")
    destination.mkdir(parents=True)
    sources = []
    for index in range(cases):
        label = "Baseline" if index == 0 else f"Case {index:02d}"
        folder = destination / f"case-{index:02d}"
        for name in ("fullkeyinfo", "period", "data"):
            (folder / name).mkdir(parents=True)
        with duckdb.connect() as con:
            con.execute("CREATE TABLE keys (SeriesId INTEGER, ParentClassName VARCHAR, CollectionName VARCHAR, ChildClassName VARCHAR, ChildObjectName VARCHAR, ChildObjectCategoryName VARCHAR, PropertyName VARCHAR, PhaseName VARCHAR, PeriodTypeName VARCHAR, TimesliceName VARCHAR, SampleName VARCHAR, ModelName VARCHAR, UnitValue VARCHAR, BandId INTEGER)")
            for series, tech in enumerate(("Gas-CC", "UPV", "Onshore Wind"), 1):
                con.execute("INSERT INTO keys VALUES (?, 'System','Generators','Generator',?,?,'Generation','LT','Year','All Periods','Mean',?,'GWh',1)", [series, tech + " plant",tech,label])
            con.execute("CREATE TABLE periods AS SELECT i::INTEGER AS PeriodId, TIMESTAMP '2030-01-01' + i * INTERVAL '1 year' AS StartDate, TIMESTAMP '2030-01-01' + (i+1) * INTERVAL '1 year' AS EndDate FROM range(5) t(i)")
            con.execute("CREATE TABLE vals AS SELECT SeriesId, PeriodId, CASE SeriesId WHEN 1 THEN 1000-?*(PeriodId+1) WHEN 2 THEN 100+?*(PeriodId+1) ELSE 200+?*(PeriodId+1) END AS Value FROM keys CROSS JOIN periods",[index*3,index*2,index])
            for table, name in (("keys","fullkeyinfo"),("periods","period"),("vals","data")):
                con.execute(f"COPY {table} TO ? (FORMAT PARQUET)",[str(folder/name/"part.parquet")])
        sources.append(Source(label,path=str(folder)))
    query = {"collection":"SystemGenerators","properties":"Generation","phase":"LTPlan","period":"Year",
        "sample":"Mean","band_id":1,"timeslice":"All Periods","aggregate_by":"category","aggregate_type":"SUM"}
    plot = {**PRESETS["Scenario stacks"],"baseline":"Baseline","comparison":"Difference",
            "series_order":["Gas-CC","UPV","Onshore Wind"],"columns":3}
    workspace = destination/"workspace.private.json"
    workspace.write_text(json.dumps(make_workspace(sources,query,plot),indent=2),encoding="utf-8")
    return workspace


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default="work/pivot-demo")
    parser.add_argument("--cases",type=int,default=36)
    args=parser.parse_args()
    print(create_demo(args.output,args.cases))
