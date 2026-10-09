"""Create fictional annual results and a ready-to-run report bundle."""
import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from pxbp.bundles import make_bundle
from pxbp.report_library import PRESETS
from pxbp.sources import Source


def create_demo(destination, cases=4):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError("Choose a new demo directory")
    if not 2<=cases<=36:raise ValueError("Choose 2–36 demo solutions")
    destination.mkdir(parents=True)
    sources=[]
    for case in range(cases):
        label="Baseline" if case==0 else f"Case {case:02d}"
        folder=destination/f"case-{case:02d}"
        for name in ("fullkeyinfo","period","data"):(folder/name).mkdir(parents=True)
        keys,values=[],[]
        seen=set()
        for definition in PRESETS.values():
            key=(definition["collection"],definition["property"])
            if key in seen:continue
            seen.add(key)
            family=definition["family"]
            unit={"power":"MW","energy":"GWh","storage-energy":"MWh","money":"$000","native":"ton"}[family]
            scope=definition["class"]
            objects={"Generator":[("Gas plant","Gas-CC"),("Solar plant","UPV")],
                "Battery":[("Short duration","Battery"),("Long duration","Battery")],
                "Region":[("Outer region","Regional"),("Inner region","Regional")],
                "Emission":[("Emission A","Emissions"),("Emission B","Emissions")]}[scope]
            for object_index,(obj,category) in enumerate(objects):
                series=len(keys)+1
                keys.append({"SeriesId":series,"ParentClassName":"System","ParentObjectName":"System",
                    "CollectionName":definition["collection"].removeprefix("System"),"ChildClassName":scope,
                    "ChildObjectName":obj,"ChildObjectCategoryName":category,"PropertyName":definition["property"],
                    "PhaseName":"LT","PhaseId":0,"PeriodTypeName":"Year","PeriodTypeId":4,"TimesliceName":"All Periods",
                    "SampleName":"Mean","SampleId":0,"ModelName":label,"ModelId":1,"UnitValue":unit,"BandId":1})
                for period in range(3):
                    base={"power":1000,"energy":100,"storage-energy":4000,"money":400000,"native":10000}[family]
                    value=base*(1+.1*period)*(1+.05*case)*(1+.3*object_index)
                    values.append({"SeriesId":series,"PeriodId":period,"Value":value})
        periods=pd.DataFrame({"PeriodId":range(3),"PeriodTypeId":[4]*3,
            "StartDate":pd.date_range("2030-01-01",periods=3,freq="YS"),"EndDate":pd.date_range("2031-01-01",periods=3,freq="YS")})
        with duckdb.connect() as con:
            for name,frame in (("fullkeyinfo",pd.DataFrame(keys)),("data",pd.DataFrame(values)),("period",periods)):
                con.register("table_data",frame);con.execute("COPY table_data TO ? (FORMAT PARQUET)",[str(folder/name/"part.parquet")])
        sources.append(Source(label,path=str(folder)))
    config=make_bundle(sources,"Baseline",colors={"Short duration":"#FF4A88","Long duration":"#CC015C"},series_order=["Gas-CC","UPV"])
    path=destination/"bundle.private.json";path.write_text(json.dumps(config,indent=2),encoding="utf-8")
    return path


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default="work/report-library-demo")
    parser.add_argument("--cases",type=int,default=4)
    args=parser.parse_args();print(create_demo(args.output,args.cases))
