"""Create synthetic annual reports without cloud credentials or a native API."""
import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd


def create_demo(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("Choose a new demo folder")
    destination.mkdir(parents=True)
    definitions = [
        ("Generators", "Generator", "Solar A", "Capacity Built", "MW", 100),
        ("Generators", "Generator", "Solar A", "Installed Capacity", "MW", 400),
        ("Generators", "Generator", "Solar A", "Total Cost", "$000", 100000),
        ("Generators", "Generator", "Solar A", "Build Cost", "$000", 20000),
        ("Generators", "Generator", "Solar A", "Generation", "GWh", 700),
        ("Batteries", "Battery", "Battery A", "Generation Capacity Built", "MW", 50),
        ("Batteries", "Battery", "Battery A", "Generation Capacity", "MW", 150),
        ("Batteries", "Battery", "Battery A", "Total Cost", "$000", 10000),
        ("Constraints", "Constraint", "Gate A", "Hours Binding", "h", 30),
        ("Constraints", "Constraint", "Gate A", "RHS", "-", 500),
        ("Generators", "Generator", "Upgrade A", "Build Cost", "$000", 5000),
        ("Generators", "Generator", "Upgrade A", "Units Built", "-", 1),
        ("Zones", "Zone", "Region A", "Load", "GWh", 800),
        ("Zones", "Zone", "Region A", "Capacity Reserve Margin", "%", 16),
    ]
    for case, scale in (("case-a", 1), ("case-b", 1.2)):
        root = destination/case
        con = duckdb.connect()
        keys = pd.DataFrame([dict(SeriesId=i, ParentClassName="System", CollectionName=c, ChildClassName=cl,
            ChildObjectName=name, ChildObjectCategoryName="Demo", PropertyName=prop, PhaseName="LTPlan", PeriodTypeName="Year",
            TimesliceName="All Periods", SampleName="Mean", ModelName="Demo", UnitValue=unit, BandId=1)
            for i,(c,cl,name,prop,unit,value) in enumerate(definitions,1)])
        vals = pd.DataFrame([dict(SeriesId=i, PeriodId=year, Value=value*scale*(1+(year-2031)*.1))
            for i,(*_,value) in enumerate(definitions,1) for year in (2031,2032)])
        con.execute("CREATE TABLE periods AS SELECT i::INTEGER PeriodId,make_timestamp(i::BIGINT,1,1,0,0,0) StartDate,make_timestamp((i+1)::BIGINT,1,1,0,0,0) EndDate FROM range(2031,2033) t(i)")
        for table,folder in (("keys","fullkeyinfo"),("vals","data"),("periods","period")):
            (root/folder).mkdir(parents=True)
            con.execute(f"COPY (SELECT * FROM {table}) TO ? (FORMAT PARQUET)",[str(root/folder/'part.parquet')])
        con.close()
    assets=[dict(collection="System"+c,object_name=n,technology=t,sector=sector,planning_region="Region A",owner="Owner A",state="State A",mapping_status="synthetic current mapping")
        for c,n,t,sector in [("Generators","Solar A","UPV","Generation"),("Batteries","Battery A","Battery","Generation"),("Generators","Upgrade A","Flowgate","Flowgate"),("Constraints","Gate A","Flowgate","Flowgate"),("Zones","Region A","System/zone","Zone")]]
    next(a for a in assets if a['object_name']=='Upgrade A')['report_object_name']='Gate A'
    for asset in assets:
        if asset['object_name'] in ('Upgrade A','Gate A'):
            asset['related_asset']='Upgrade A'
    metrics=[]
    def add(key,title,family,temporal,queries,section,detail=False,mapped=False):
        metric=dict(id=key,title=title,family=family,temporal=temporal,section=section,queries=[dict(collection="System"+c,properties=p,phase="LTPlan",period="Year",sample="Mean",timeslice="All Periods") for c,p in queries])
        if detail:metric.update(asset_detail=True,geographies=['object_name'])
        if mapped:metric['object_label']='mapped'
        metrics.append(metric)
    add('new','New capacity','power','sum',[('Generators','Capacity Built'),('Batteries','Generation Capacity Built')],'Capacity')
    add('installed','Installed capacity','power','snapshot',[('Generators','Installed Capacity'),('Batteries','Generation Capacity')],'Capacity')
    add('cost','Generator and battery total cost','money','sum',[('Generators','Total Cost'),('Batteries','Total Cost')],'Costs')
    add('generation','Generation','energy','sum',[('Generators','Generation')],'Energy')
    add('load','Zonal load','energy','sum',[('Zones','Load')],'Zonal results',True)
    add('reserve','Reserve margin','percent','snapshot',[('Zones','Capacity Reserve Margin')],'Zonal results',True)
    add('binding','Binding hours','hours','sum',[('Constraints','Hours Binding')],'Flowgate explorer',True)
    add('rhs','Reported constraint RHS','native','snapshot',[('Constraints','RHS')],'Flowgate explorer',True)
    add('upgrade_cost','Upgrade build cost','money','sum',[('Generators','Build Cost')],'Flowgate explorer',True,True)
    metrics[-1]['sectors']=['Flowgate']
    add('upgrade_timing','Upgrade timing','count','sum',[('Generators','Units Built')],'Flowgate explorer',True,True)
    metrics[-1]['sectors']=['Flowgate']
    (destination/'sources.json').write_text(json.dumps({'sources':[{'label':'Case A','path':'case-a'},{'label':'Case B','path':'case-b'}]},indent=2),encoding='utf-8')
    (destination/'report-spec.json').write_text(json.dumps(dict(title='Annual reporting demonstration',years=[2031,2032],assets=assets,metrics=metrics),indent=2),encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='work/demo-annual')
    print(create_demo(parser.parse_args().output))
