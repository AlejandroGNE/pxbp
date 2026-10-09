"""Create fictional annual and hourly Parquets for every analytical recipe."""
import argparse
import json
import math
from pathlib import Path

import duckdb
import pandas as pd

from pxbp.analytics import make_analysis
from pxbp.analytics_catalog import MEASURES,RECIPES
from pxbp.sources import Source


def create_demo(destination,cases=3):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError("Choose a new demo directory")
    if not 2<=cases<=36:raise ValueError("Choose 2–36 solutions")
    destination.mkdir(parents=True);sources=[]
    hours=pd.date_range('2030-01-30',periods=96,freq='h')
    for case in range(cases):
        label='Baseline' if case==0 else f'Case {case:02d}'
        folder=destination/f'case-{case:02d}'
        for name in ('fullkeyinfo','data','period'):(folder/name).mkdir(parents=True)
        keys=[];values=[];periods=[]
        for index,year in enumerate(range(2030,2033)):
            periods.append(dict(PeriodId=index,PeriodTypeId=4,StartDate=pd.Timestamp(year,1,1),EndDate=pd.Timestamp(year,12,31)))
        periods.extend(dict(PeriodId=100+i,PeriodTypeId=0,StartDate=start,EndDate=start+pd.Timedelta(1,unit="h")) for i,start in enumerate(hours))
        objects={'Generator':[('Gas 1','Gas-CC'),('Gas 2','Gas-CC'),('Solar 1','UPV'),('Wind 1','Wind')],
            'Battery':[('Battery 2h','Battery'),('Battery 4h','Battery')],
            'Region':[('System region','Regional')],'Emission':[('Emission A','Emissions')]}
        for identifier,m in MEASURES.items():
            for object_index,(obj,category) in enumerate(objects[m['scope']]):
                series=len(keys)+1;interval=m['period']=='Interval';family=m['family']
                unit={'energy':'GWh' if m['scope']!='Battery' or m['property'] in {'Generation','Load','Net Generation'} else 'MWh',
                    'power':'MW','money':'$' if interval else '$000','mass':'lb' if interval else 'ton','price':'$/MWh','percent':'%'}[family]
                keys.append(dict(SeriesId=series,ParentClassName='System',ParentObjectName='System',CollectionName=m['collection'].removeprefix('System'),
                    ChildClassName=m['scope'],ChildObjectName=obj,ChildObjectCategoryName=category,PropertyName=m['property'],PhaseName='LT',PhaseId=0,
                    PeriodTypeName=m['period'],PeriodTypeId=0 if interval else 4,TimesliceName='All Periods',SampleName='Mean',SampleId=0,
                    ModelName=label,ModelId=1,UnitValue=unit,BandId=1))
                for i in range(96 if interval else 3):
                    factor=(1+.08*case)*(1+.3*object_index)
                    if interval:
                        daily=math.sin((i%24)/24*math.pi*2)
                        base={'power':1000*(1+.3*daily),'energy':10,'money':100000,'mass':2000,'price':35+45*daily,'percent':50+25*daily}[family]
                        if identifier=='unserved-power':base=5 if i in {40,41,42} else 0
                        if identifier=='battery-net-power':base=200*daily
                        if identifier=='battery-input':base=max(0,-200*daily)
                        if identifier=='battery-output':base=max(0,200*daily)
                        if identifier=='curtailed-power':base=max(0,100*daily)
                        if category=='UPV':base=max(0,base*math.sin((i%24-6)/12*math.pi))
                    else:
                        base={'power':1000,'energy':4000 if unit=='MWh' else 100,'money':400000,'mass':10000,'price':40,'percent':35}[family]*(1+.1*i)
                        if identifier=='capacity-factor':base=20+10*object_index
                    values.append(dict(SeriesId=series,PeriodId=100+i if interval else i,Value=base*factor))
        with duckdb.connect() as con:
            for name,frame in (('fullkeyinfo',pd.DataFrame(keys)),('data',pd.DataFrame(values)),('period',pd.DataFrame(periods))):
                con.register('rows',frame);con.execute('COPY rows TO ? (FORMAT PARQUET)',[str(folder/name/'part.parquet')])
        sources.append(Source(label,path=str(folder)))
    cfg=make_analysis(sources,'Baseline',date_from='2030-01-30',date_to='2030-02-02',recipes=list(RECIPES),
        colors={'Battery 2h':'#FF4A88','Battery 4h':'#CC015C'},series_order=['Gas-CC','Wind','UPV'])
    path=destination/'analysis.private.json';path.write_text(json.dumps(cfg,indent=2),encoding='utf-8');return path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='work/analysis-demo');parser.add_argument('--cases',type=int,default=3)
    args=parser.parse_args();print(create_demo(args.output,args.cases))
