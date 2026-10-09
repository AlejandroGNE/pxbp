"""Bounded analytical workspaces with explicit units, time weights, and coverage."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import threading

import duckdb
import numpy as np
import pandas as pd

from .analytics_catalog import MEASURES, FACTORS, RECIPES, DEFAULT_ANALYSIS, get_recipe
from .cache import query_cached
from .comparison import MODES, compare
from .pivot import IDENTITY
from .report_library import compact
from .sources import Source, Selection, COLUMNS, Cancelled
from .workspace import PLOT_DEFAULTS, CHART_TYPES, validate_plot

KEYS = ["scenario","model_name","collection_name","class_name","object_name","category_name","phase_name",
        "period_type_name","timeslice_name","sample_name","band_id","start_date","end_date"]
TIME_KEYS = [c for c in KEYS if c not in {"collection_name","class_name","object_name","category_name"}]
ANALYSIS_CHARTS = [*CHART_TYPES,"Heatmap","Scatter"]
ALLOWED_FILTERS = {"phase","sample","model","band_id","timeslice"}


def make_analysis(sources, baseline, *, selected_sources=None, date_from="2030-01-01", date_to="2030-01-14", filters=None, colors=None, series_order=None, recipes=None):
    return validate_analysis({"kind":"analysis-workspace","version":1,"title":"Scenario analysis",
        "sources":[{"label":s.label, **({"path":str(s.path)} if s.path else {"solution_id":s.solution_id})} for s in sources],
        "selected_sources":selected_sources or [s.label for s in sources],"baseline":baseline,
        "date_from":date_from,"date_to":date_to,"query_filters":filters or {},"colors":colors or {},"series_order":series_order or [],
        "annual_from":None,"annual_to":None,"region":"","sections":[{"id":r,"preset":r} for r in (recipes or DEFAULT_ANALYSIS)]})[1]


def date_bounds(config):
    start=pd.Timestamp(config["date_from"]);end=pd.Timestamp(config["date_to"])
    if len(config["date_to"])==10:end += pd.Timedelta(1,unit="d")-pd.Timedelta(1,unit="us")
    if pd.isna(start) or pd.isna(end) or start>end or start.tzinfo is not None or end.tzinfo is not None:
        raise ValueError("Use ordered local model dates without timezone suffixes")
    if end-start>pd.Timedelta(366,unit="d"):raise ValueError("An interval workspace covers at most 366 days; create separate year workspaces")
    return start,end


def analysis_plot(recipe,config,overrides=None):
    plot={**PLOT_DEFAULTS,"x":{"annual":"year","interval":"start_date","monthly":"month_date","duration":"exceedance","heatmap":"start_date","profile":"hour","histogram":"metric_x","scatter":"start_date","statistics":"object_name"}[recipe["resolution"]],
        "series":recipe["series"],"facet":recipe["facet"],"chart_type":recipe["chart"],"baseline":config["baseline"],"columns":1,
        "net_total":recipe["stack"],"colors":config.get("colors",{}),"series_order":config.get("series_order",[]),**(overrides or {})}
    original=plot["chart_type"]
    if original not in ANALYSIS_CHARTS:raise ValueError("Unsupported analysis chart")
    if original in {"Stacked Bar","Stacked Area"} and plot["series"]=="scenario":raise ValueError("Use an unstacked chart when scenarios are the series")
    if plot["scale"]!=1 or plot["unit_label"]:raise ValueError("Analysis recipes set their own units; display scaling cannot override them")
    if original=="Heatmap" and recipe["resolution"]!="heatmap":raise ValueError("Choose a calendar heatmap recipe for hour/date charts")
    if original=="Scatter" and recipe["operation"]!="scatter":raise ValueError("Scatter plots require paired measures")
    if recipe["operation"]=="scatter" and original!="Scatter":raise ValueError("Paired measures require a scatter plot")
    if recipe["resolution"] in {"duration","histogram","statistics"} and original in {"Stacked Bar","Stacked Area"}:raise ValueError("Distributions and statistics cannot be stacked")
    expected={"annual":"year","interval":"start_date","monthly":"month_date","duration":"exceedance","heatmap":"start_date","profile":"hour","histogram":"metric_x","scatter":"start_date","statistics":"object_name"}[recipe["resolution"]]
    if plot["x"]!=expected or plot["operation"]!="sum":raise ValueError("Recipe axes and aggregation are fixed by their calculation")
    # Preserve region/emission/battery identity even when a user chooses another chart type.
    if recipe["scope"]=="object" and recipe["operation"] not in {"balance","statistics","reliability"} and original not in {"Heatmap","Scatter"}:
        if plot["series"]!="scenario" or plot["facet"]!="object_name":raise ValueError("This recipe preserves separate reported objects")
    plot["chart_type"]="Dot-Line" if original in {"Heatmap","Scatter"} else original
    plot=validate_plot(plot,[s["label"] for s in config["sources"]]);plot["chart_type"]=original
    return plot


def validate_analysis(config,base_dir=None):
    allowed={"kind","version","title","sources","selected_sources","baseline","date_from","date_to","annual_from","annual_to","query_filters","region","colors","series_order","sections"}
    if not isinstance(config,dict) or set(config)-allowed or config.get("kind")!="analysis-workspace" or config.get("version")!=1:raise ValueError("Expected a version 1 analysis-workspace")
    config=deepcopy(config);sources=[]
    for item in config.get("sources",[]):
        if not isinstance(item,dict) or set(item) not in ({"label","path"},{"label","solution_id"}):raise ValueError("Sources require label and path or solution_id")
        if "path" in item:item["path"]=str(((Path(base_dir) if base_dir else Path.cwd())/Path(item["path"]).expanduser()).resolve())
        sources.append(Source(**item))
    labels=[s.label for s in sources]
    if not labels or len(set(labels))!=len(labels):raise ValueError("Use uniquely labelled sources")
    selected=config.setdefault("selected_sources",labels)
    if not isinstance(selected,list) or not selected or set(selected)-set(labels) or config.get("baseline") not in selected:raise ValueError("Selected sources must include the configured baseline")
    config.setdefault("title","Scenario analysis")
    if not isinstance(config["title"],str) or not config["title"].strip():raise ValueError("Use a nonempty title")
    filters=config.setdefault("query_filters",{})
    if not isinstance(filters,dict) or set(filters)-ALLOWED_FILTERS:raise ValueError("Shared filters support phase, sample, model, band_id, timeslice")
    Selection({"collection":"SystemGenerators","properties":["Generation"],**filters})
    for key in ("annual_from","annual_to"):
        config.setdefault(key,None)
        if config[key] is not None and (type(config[key]) is not int or not 1900<=config[key]<=2200):raise ValueError("Annual bounds must be years or null")
    if config["annual_from"] and config["annual_to"] and config["annual_from"]>config["annual_to"]:raise ValueError("Annual bounds are reversed")
    config.setdefault("region","")
    if not isinstance(config["region"],str):raise ValueError("Region must be an exact object name or blank")
    date_bounds(config)
    sections=config.get("sections")
    if not isinstance(sections,list) or not 1<=len(sections)<=100:raise ValueError("Use 1–100 analysis sections")
    ids=set()
    for section in sections:
        if not isinstance(section,dict) or set(section)-{"id","preset","title","views","plot","formula"}:raise ValueError("Unknown section fields")
        ident=section.get("id","")
        if not isinstance(ident,str) or not ident or any(not(c.isalnum() or c in "-_") for c in ident) or ident in ids:raise ValueError("Use unique safe section IDs")
        ids.add(ident)
        recipe=section_recipe(section)
        section.setdefault("title",recipe["title"])
        if not isinstance(section["title"],str):raise ValueError("Section title must be text")
        section.setdefault("views",["Absolute"] if recipe["operation"]=="scatter" else ["Absolute","Difference"])
        if not isinstance(section["views"],list) or not section["views"] or len(set(section["views"]))!=len(section["views"]) or set(section["views"])-set(MODES):raise ValueError("Choose unique comparison modes")
        if recipe["operation"]=="scatter" and section["views"]!=["Absolute"]:raise ValueError("Scatter relationships use Absolute view only")
        if set(section.get("plot",{}))&{"baseline","comparison"}:raise ValueError("Sections share the workspace baseline and views")
        plot=analysis_plot(recipe,config,section.get("plot"))
        if plot["chart_type"] in {"Stacked Bar","Stacked Area"} and set(section["views"])&{"Ratio","Percent change"}:raise ValueError("Percent changes and ratios cannot be stacked")
    return sources,config


def read_analysis(path):
    path=Path(path).resolve();return validate_analysis(json.loads(path.read_text(encoding="utf-8-sig")),path.parent)


def section_recipe(section):
    if section.get("preset")!="custom":return get_recipe(section.get("preset"))
    formula=section.get("formula",{})
    if not isinstance(formula,dict) or set(formula)-{"left","right","operation","scope"}:raise ValueError("Custom formulas support left, right, operation, scope")
    left,right=formula.get("left"),formula.get("right")
    op=formula.get("operation")
    if left not in MEASURES or right not in MEASURES or op not in {"ratio","difference","fraction","weighted"}:raise ValueError("Choose reported inputs and a supported calculation")
    a,b=MEASURES[left],MEASURES[right]
    if a["period"]!="Year" or b["period"]!="Year" or a["scope"]!=b["scope"]:raise ValueError("Custom annual formulas require the same reported class")
    if op in {"difference","fraction"} and a["family"]!=b["family"]:raise ValueError("Difference/share inputs need compatible units")
    scope=formula.get("scope","object")
    if scope not in {"object","category"}:raise ValueError("Custom scope is object or category")
    if scope=="category" and a["scope"]!="Generator":raise ValueError("Only generator formulas aggregate technology categories")
    return dict(title=section.get("title","Custom calculated measure"),inputs=[left,right],operation=op,scope=scope,resolution="annual",unit="",scale=1,chart="Dot-Line",series="scenario",facet="category_name" if scope=="category" else "object_name",stack=False,
        note=f"{op}: {a['property']} and {b['property']}; {scope} scope. Ratios use summed operands; weighted means use distinct asset weights. No Python expressions are executed.")


def validate_measure(frame,definition):
    data=frame.copy()
    if data.empty:return data
    if not data.class_name.map(compact).eq(compact(definition["scope"])).all() or not data.property_name.map(compact).eq(compact(definition["property"])).all():raise ValueError("Unexpected reported class or property")
    if not data.period_type_name.map(compact).eq(compact(definition["period"])).all():raise ValueError("Unexpected reported period")
    for name in ("model_name","phase_name","sample_name","band_id","timeslice_name"):
        if data.groupby("scenario",observed=True)[name].nunique(dropna=False).gt(1).any():raise ValueError("Choose one model, phase, sample, band, and time slice per solution")
    if data.duplicated(KEYS).any():raise ValueError("Duplicate measurement identities or property aliases")
    if definition["period"]=="Year" and data.assign(year=data.start_date.dt.year).duplicated([c for c in KEYS if c not in {"start_date","end_date"}]+["year"]).any():raise ValueError("Duplicate annual asset/year measurements")
    if definition["family"]!="mass":
        factors,unit=FACTORS[definition["family"]]
        if set(data.unit)-set(factors):raise ValueError("Unexpected reported units: "+", ".join(sorted(set(data.unit)-set(factors))))
        data["value"]=data.value*data.unit.map(factors);data["unit"]=unit
    if definition["period"]=="Interval":
        data["hours"]=(data.end_date-data.start_date).dt.total_seconds()/3600
        if data.end_date.isna().any() or not data.hours.gt(0).all():raise ValueError("Intervals need explicit positive start/end durations")
        for _,group in data.groupby([c for c in KEYS if c not in {"start_date","end_date"}],dropna=False,observed=True):
            group=group.sort_values("start_date")
            if (group.start_date.iloc[1:].to_numpy()<group.end_date.iloc[:-1].to_numpy()).any():raise ValueError("Overlapping intervals cannot be aggregated")
    data["phase_name"]=data.phase_name.replace({"LTPlan":"LT","STSchedule":"ST"})
    return data


class MeasurementStore:
    def __init__(self,sources,config,cache_dir,cancel,progress,max_rows,timeout,refresh):
        self.sources,self.config,self.cache_dir,self.cancel,self.progress=sources,config,cache_dir,cancel,progress
        self.remaining,self.limit,self.timeout,self.refresh=max_rows,max_rows,timeout,refresh
        self.frames,self.raw,self.audit={},{},{}

    def get(self,identifier):
        if identifier in self.frames:return self.frames[identifier].copy()
        definition=MEASURES[identifier]
        query={"collection":definition["collection"],"properties":list(dict.fromkeys([definition["property"],definition["property"].replace(" ","")])),
            "parent":"System","phase":"LTPlan","sample":"Mean","band_id":1,"timeslice":"All Periods",
            "period":definition["period"],"aggregate_by":definition["aggregate"],**self.config.get("query_filters",{})}
        if definition["aggregate"]!="none":query["aggregate_type"]="SUM"
        if definition["period"]=="Interval":
            start,end=date_bounds(self.config);query.update(date_from=start.isoformat(),date_to=end.isoformat())
        else:
            if self.config["annual_from"]:query["date_from"]=f"{self.config['annual_from']}-01-01"
            if self.config["annual_to"]:query["date_to"]=f"{self.config['annual_to']}-12-31"
        if definition["scope"]=="Region" and self.config.get("region"):query["child"]=[self.config["region"]]
        frames,raws,coverage=[],[],[]
        for source in self.sources:
            if self.cancel.is_set():raise Cancelled("Analysis cancelled")
            if self.remaining<1:raise ValueError("Analysis row budget exhausted; narrow dates, sources, or sections")
            self.progress(f"{identifier}: {source.label}")
            try:
                parts=[]
                for batch in query_cached([source],Selection(query,max_rows=min(1000000,self.remaining),timeout=self.timeout),self.cache_dir,self.cancel,refresh=self.refresh):
                    self.remaining-=len(batch.frame);parts.append(batch.frame)
                raw=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
                if raw.empty:coverage.append(dict(scenario=source.label,status="unavailable",reason="No reported measurements"));continue
                raws.append(raw)
                data=validate_measure(raw,definition)
                if definition["period"]=="Interval":
                    start,end=date_bounds(self.config);end+=pd.Timedelta(1,unit="us")
                    original=data.hours.copy()
                    data["start_date"]=data.start_date.clip(lower=start)
                    data["end_date"]=data.end_date.clip(upper=end)
                    data["hours"]=(data.end_date-data.start_date).dt.total_seconds()/3600
                    if definition["family"] in {"money","mass"}:data["value"]*=data.hours/original
                    data=data[data.hours.gt(0)]
                frames.append(data);coverage.append(dict(scenario=source.label,status="available",rows=len(raw),models=sorted(set(raw.model_name)),units=sorted(set(raw.unit))))
            except (Cancelled,TimeoutError):raise
            except Exception as exc:
                if "Row limit" in str(exc) or "budget" in str(exc):raise
                coverage.append(dict(scenario=source.label,status="incompatible",reason=str(exc)))
        self.frames[identifier]=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
        self.raw[identifier]=pd.concat(raws,ignore_index=True) if raws else pd.DataFrame(columns=COLUMNS)
        self.audit[identifier]=dict(query=query,definition=definition,coverage=coverage)
        return self.frames[identifier].copy()


def reduce_assets(data,scope):
    if data.empty:return data.copy()
    if scope=="object":return data.copy()
    keys=[c for c in KEYS if c!="object_name"]+["unit","property_name"]
    if scope=="system":keys.remove("category_name")
    values=data.groupby(keys,as_index=False,dropna=False,observed=True).value.sum(min_count=1)
    if scope=="system":values["category_name"]="All reported generators"
    values["object_name"]=values.category_name
    if "hours" in data:values["hours"]=(values.end_date-values.start_date).dt.total_seconds()/3600
    return values


def pair(left,right,*,cross=False,how="left"):
    keys=TIME_KEYS if cross else KEYS
    if cross and right.groupby(TIME_KEYS,dropna=False,observed=True).size().gt(1).any():raise ValueError("Choose exactly one region for cross-class denominators")
    cols=keys+["value","unit"]
    data=left.merge(right[cols].rename(columns={"value":"operand","unit":"operand_unit"}),on=keys,how=how,validate="many_to_one")
    if not left.empty:
        data["unit"]=data.unit.fillna(left.unit.iloc[0]);data["property_name"]=data.property_name.fillna(left.property_name.iloc[0])
    return data


def divide(numerator,denominator):
    return (numerator/denominator).where(denominator.ne(0)&numerator.notna()&denominator.notna()).replace([np.inf,-np.inf],np.nan)


def split_time(data,by,mode,weight=None):
    first=data.start_date.dt.to_period("M") if by=="month" else data.start_date.dt.floor("h")
    last=(data.end_date-pd.Timedelta(1,unit="ns")).dt.to_period("M") if by=="month" else (data.end_date-pd.Timedelta(1,unit="ns")).dt.floor("h")
    crossing=first.ne(last)
    if not crossing.any():return data.copy()
    rows=[]
    for row in data[crossing].to_dict("records"):
        cur=row["start_date"];end=row["end_date"];duration=row["hours"]
        while cur<end:
            stop=min(end,(cur.to_period("M").to_timestamp()+pd.offsets.MonthBegin(1)) if by=="month" else cur.floor("h")+pd.Timedelta(1,unit="h"))
            hours=(stop-cur).total_seconds()/3600
            fragment={**row,"start_date":cur,"end_date":stop,"hours":hours}
            if mode=="sum":fragment["value"]=row["value"]*hours/duration
            if weight:fragment[weight]=row[weight]*hours/duration
            rows.append(fragment);cur=stop
    return pd.concat([data[~crossing],pd.DataFrame(rows)],ignore_index=True)


def time_group(data,by,mode,weight=None):
    data=split_time(data,by,mode,weight)
    data["bucket"]=data.start_date.dt.to_period("M").dt.to_timestamp() if by=="month" else data.start_date.dt.floor("h") if by=="calendar-hour" else data.start_date.dt.hour
    keys=[c for c in KEYS if c not in {"start_date","end_date"}]+["unit","property_name","bucket"]
    data["_numerator"]=data.value if mode=="sum" else data.value*data.hours if weight is None else data.value*data[weight]
    data["_weight"]=data.hours if weight is None else data[weight]
    grouped=data.groupby(keys,dropna=False,observed=True,as_index=False).agg(_value=("_numerator",lambda v:v.sum(min_count=1)),_weight=("_weight",lambda v:v.sum(min_count=1)),observed_hours=("hours","sum"),_invalid=("value",lambda v:v.isna().any()))
    grouped["value"]=(grouped._value if mode=="sum" else divide(grouped._value,grouped._weight)).where(~grouped._invalid)
    if by=="month":
        grouped["start_date"]=grouped.bucket;grouped["end_date"]=grouped.bucket+pd.offsets.MonthBegin(1)
        grouped["month_date"]=grouped.bucket
        grouped["partial_month"]=grouped.observed_hours.lt((grouped.end_date-grouped.start_date).dt.total_seconds()/3600-1e-6)
    elif by=="calendar-hour":
        grouped["start_date"]=grouped.bucket;grouped["end_date"]=grouped.bucket+pd.Timedelta(1,unit="h");grouped["hour"]=grouped.start_date.dt.hour
    else:
        grouped["hour"]=grouped.bucket;grouped["start_date"]=pd.Timestamp("2000-01-01")+pd.to_timedelta(grouped.bucket,unit="h");grouped["end_date"]=grouped.start_date+pd.Timedelta(1,unit="h")
    return grouped.drop(columns=["bucket","_value","_weight","_invalid"])


def weighted_quantiles(values,hours,percent):
    order=np.argsort(values);values=np.asarray(values)[order];hours=np.asarray(hours)[order]
    cumulative=np.cumsum(hours)
    if not len(values) or cumulative[-1]<=0:return np.full(len(percent),np.nan)
    return values[np.minimum(np.searchsorted(cumulative,np.asarray(percent)*cumulative[-1],side="left"),len(values)-1)]


def distributions(data,config,operation):
    results=[];keys=[c for c in KEYS if c not in {"start_date","end_date"}]+["unit","property_name"]
    edges=np.linspace(data.value.min(),data.value.max() if data.value.max()!=data.value.min() else data.value.min()+1,31) if operation=="histogram" else None
    for _,group in data.groupby(keys,dropna=False,observed=True,sort=False):
        base=group.iloc[0].to_dict()
        if operation=="duration":
            points=np.arange(101);values=weighted_quantiles(group.value.to_numpy(),group.hours.to_numpy(),1-points/100)
            rows=[{**base,"value":value,"exceedance":float(p)} for p,value in zip(points,values)]
        else:
            counts,_=np.histogram(group.value,bins=edges,weights=group.hours)
            rows=[{**base,"value":value,"metric_x":float((lo+hi)/2),"bin_lower":float(lo),"bin_upper":float(hi),"x_unit":base["unit"],"unit":"hours"} for value,lo,hi in zip(counts,edges[:-1],edges[1:])]
        for row in rows:row.update(start_date=date_bounds(config)[0],end_date=date_bounds(config)[1],observed_hours=float(group.hours.sum()),observation_count=len(group))
        results.extend(rows)
    return pd.DataFrame(results)


def statistics(data,config,operation):
    rows=[];keys=[c for c in KEYS if c not in {"start_date","end_date"}]+["unit","property_name"]
    for _,group in data.groupby(keys,dropna=False,observed=True):
        base=group.iloc[0].to_dict();q=weighted_quantiles(group.value.to_numpy(),group.hours.to_numpy(),[.05,.5,.95])
        measures=[("Minimum",group.value.min(),base["unit"]),("Maximum",group.value.max(),base["unit"]),("Time-weighted mean",np.average(group.value,weights=group.hours),base["unit"]),
                  ("5th percentile",q[0],base["unit"]),("Median",q[1],base["unit"]),("95th percentile",q[2],base["unit"])]
        if operation=="reliability":
            group=group.sort_values("start_date");longest=current=0;previous=None
            for row in group.itertuples():
                current=current+row.hours if row.value>0 and (previous is None or previous==row.start_date) else row.hours if row.value>0 else 0
                longest=max(longest,current);previous=row.end_date
            measures=[("Observed unserved energy",(group.value*group.hours).sum()/1000,"GWh"),("Observed unserved hours",group.loc[group.value.gt(0),"hours"].sum(),"hours"),("Longest observed event",longest,"hours")]
        elif base["unit"]=="$/MWh":measures.append(("Negative-price hours",group.loc[group.value.lt(0),"hours"].sum(),"hours"))
        elif base["unit"]=="MW":
            measures=[(label,value*.001 if unit=="MW" else value,"GW" if unit=="MW" else unit) for label,value,unit in measures]
            measures.append(("Observed energy",(group.value*group.hours).sum()/1000000,"TWh"))
        for label,value,unit in measures:rows.append({**base,"property_name":label,"value":value,"unit":unit,"start_date":date_bounds(config)[0],"end_date":date_bounds(config)[1],"observed_hours":float(group.hours.sum())})
    return pd.DataFrame(rows)


def calculate(recipe,store,config):
    inputs=[store.get(name) for name in recipe["inputs"]]
    if not inputs or inputs[0].empty:raise ValueError("No reported numerator measurements")
    a=inputs[0];op=recipe["operation"];scope=recipe["scope"]
    if op=="weighted":
        if inputs[1].value.lt(0).any():raise ValueError("Weighted means require nonnegative weights")
        data=pair(a,inputs[1],how="outer");data["_invalid"]=data.value.isna()|data.operand.isna();data["value"]=data.value*data.operand
        if scope=="category":
            data.loc[data.groupby([c for c in KEYS if c!="object_name"],dropna=False,observed=True)._invalid.transform("any"),"value"]=np.nan
        numerator=reduce_assets(data,scope);weights=data.copy();weights["value"]=weights.operand
        weights["unit"]=weights.operand_unit.fillna(inputs[1].unit.iloc[0] if not inputs[1].empty else "undefined")
        denominator=reduce_assets(weights,scope)
        data=pair(numerator,denominator);data["value"]=divide(data.value,data.operand)
    else:
        data=reduce_assets(a,scope)
        if op in {"ratio","difference","fraction","utilization","cross-ratio"}:
            if scope=="category" and op!="cross-ratio":
                matched=pair(a,inputs[1],how="outer")
                bad=matched.value.isna()|matched.operand.isna()
                grouping=[c for c in KEYS if c!="object_name"]
                invalid=matched.loc[bad,grouping].drop_duplicates()
                if not invalid.empty:
                    poisoned=data.merge(invalid.assign(_bad=True),on=grouping,how="left")
                    data.loc[poisoned._bad.fillna(False).to_numpy(),"value"]=np.nan
            b=reduce_assets(inputs[1],scope) if op!="cross-ratio" else inputs[1]
            data=pair(data,b,cross=op=="cross-ratio",how="left" if op=="cross-ratio" else "outer")
            if op=="difference":data["value"]=data.value-data.operand
            elif op=="fraction":data["value"]=100*divide(data.value,data.value+data.operand)
            elif op=="utilization":
                years=data.start_date.dt.year
                hours=pd.Series([(pd.Timestamp(int(y)+1,1,1)-pd.Timestamp(int(y),1,1)).total_seconds()/3600 for y in years],index=data.index)
                data["value"]=100*divide(data.value,data.operand*hours)
            else:
                native=data.unit.copy();other=data.operand_unit.copy();data["value"]=divide(data.value,data.operand)
                if not recipe["unit"]:data["unit"]=native.astype(str)+"/"+other.astype(str)
        elif op=="share":
            total=reduce_assets(a,"system");data=pair(data,total,cross=True);data["value"]=100*divide(data.value,data.operand)
        elif op=="change":
            prior=data.copy();prior["start_date"]=prior.start_date+pd.DateOffset(years=1);prior["end_date"]=prior.end_date+pd.DateOffset(years=1)
            # Leap-day annual end conventions are normalized to calendar years for alignment.
            data["end_date"]=pd.to_datetime(data.start_date.dt.year.astype(str)+"-12-31")
            prior["end_date"]=pd.to_datetime(prior.start_date.dt.year.astype(str)+"-12-31")
            data=pair(data,prior);data["value"]=data.value-data.operand
        elif op=="balance":
            charging=inputs[1].copy();charging["value"]=-charging.value
            data["category_name"]="Discharge | "+data.object_name;charging["category_name"]="Charge | "+charging.object_name
            data=pd.concat([data,charging],ignore_index=True)
        elif op in {"monthly-sum","monthly-mean","monthly-weighted","profile"}:
            if op=="monthly-sum":
                if MEASURES[recipe["inputs"][0]]["family"]=="power":data["value"]=data.value*data.hours;data["unit"]="MWh"
                data=time_group(data,"month","sum")
            elif op=="monthly-weighted":
                data=pair(data,inputs[1]);data["weight"]=data.operand*data.hours
                if data.operand.lt(0).any():raise ValueError("Load-weighted prices require nonnegative demand")
                # Missing price/load pairs must not silently form a smaller denominator.
                data.loc[data.operand.isna(),"value"]=np.nan
                data=time_group(data,"month","mean","weight")
            else:data=time_group(data,"hour" if op=="profile" else "month","mean")
        elif op in {"duration","histogram"}:data=distributions(data,config,op)
        elif op=="scatter":data=pair(data,inputs[1]);data["metric_x"]=data.operand*.001;data["x_unit"]="GW"
        elif op in {"statistics","reliability"}:data=statistics(data,config,op)
    if recipe["resolution"]=="heatmap":data=time_group(data,"calendar-hour","mean")
    if recipe["unit"]:data["unit"]=recipe["unit"]
    data["value"]=data.value*recipe["scale"]
    if op not in {"statistics","reliability"}:data["property_name"]=recipe["title"]
    data["year"]=data.start_date.dt.year
    if recipe["resolution"] in {"monthly","duration","profile","histogram","statistics"}:data["period_type_name"]=recipe["resolution"]
    return data


def observation_coverage(data,config):
    if "hours" not in data or data.empty:return {}
    start,end=date_bounds(config);expected=(end-start).total_seconds()/3600
    keys=[c for c in KEYS if c not in {"start_date","end_date"}]+["unit"]
    totals=data.groupby(keys,observed=True,dropna=False).hours.sum()
    return dict(expected_window_hours=expected,minimum_observed_series_hours=float(totals.min()),maximum_observed_series_hours=float(totals.max()),series_with_incomplete_window=int(totals.lt(expected-1e-5).sum()))


def build_analysis(config,cache_dir=None,*,max_rows=2000000,timeout=600,cancel=None,progress=None,refresh=False):
    sources,config=validate_analysis(config)
    sources=[s for s in sources if s.label in config["selected_sources"]]
    cancel=cancel or threading.Event();progress=progress or (lambda message:None)
    if type(max_rows) is not int or not 1<=max_rows<=10000000:raise ValueError("Analysis budget must be 1–10000000 rows")
    store=MeasurementStore(sources,config,cache_dir,cancel,progress,max_rows,timeout,refresh);results=[]
    for index,section in enumerate(config["sections"]):
        if cancel.is_set():raise Cancelled("Analysis cancelled")
        progress(f"Calculating {index+1}/{len(config['sections'])}: {section['title']}")
        recipe=section_recipe(section);plot=analysis_plot(recipe,config,section.get("plot"))
        result=dict(section=section,definition=recipe,plot=plot,views={},coverage=[],status="unavailable",diagnostics={})
        try:
            data=calculate(recipe,store,config)
            # Input/source diagnostics are separate from comparison identities.
            result["diagnostics"]["input_coverage"]={name:observation_coverage(store.frames[name],config) for name in recipe["inputs"]}
            if "partial_month" in data:result["diagnostics"]["partial_month_rows"]=int(data.partial_month.sum())
            result["diagnostics"]["undefined_metric_rows"]=int(data.value.isna().sum())
            for source in sources:
                missing=[name for name in recipe["inputs"] if source.label not in set(store.frames[name].scenario)]
                result["coverage"].append(dict(scenario=source.label,status="unavailable" if missing else "available",reason="Missing input(s): "+", ".join(missing) if missing else ""))
            keep=list(dict.fromkeys(["scenario","model_name",*IDENTITY,"object_name","category_name","start_date","end_date","year","value"]+[c for c in ("month_date","hour","exceedance","metric_x","bin_lower","bin_upper","x_unit") if c in data]))
            table=data[keep].copy()
            for field,values in plot["filters"].items():
                if field!="scenario" and values:table=table[table[field].isin(values)]
            result["calculated_table"]=table
            for mode in section["views"]:
                try:
                    viewed=compare(table,config["baseline"],mode)
                    if plot["filters"].get("scenario"):viewed=viewed[viewed.scenario.isin(plot["filters"]["scenario"])]
                    result["views"][mode]=dict(table=viewed,plot={**plot,"comparison":mode},status="available")
                except ValueError as exc:result["views"][mode]=dict(status="unavailable",reason=str(exc))
            result["status"]="complete" if all(c["status"]=="available" for c in result["coverage"]) and all(v["status"]=="available" for v in result["views"].values()) else "partial"
        except (Cancelled,TimeoutError):raise
        except Exception as exc:
            if "Row limit" in str(exc) or "budget" in str(exc):raise
            result["reason"]=str(exc)
        results.append(result)
    return dict(config=config,sections=results,query_rows=store.limit-store.remaining,measurements=store.audit,raw=store.raw)


def export_analysis(spec_path,output,cache_dir=None,*,max_rows=2000000,timeout=600,progress=None):
    _,config=read_analysis(spec_path);output=Path(output).resolve()
    if output.exists():raise ValueError("Analysis output exists; choose a new directory")
    result=build_analysis(config,cache_dir,max_rows=max_rows,timeout=timeout,progress=progress)
    from .analytics_plotting import offline_analysis_document
    document=offline_analysis_document(result)
    output.mkdir(parents=True)
    try:
        (output/"analysis.html").write_text(document,encoding="utf-8")
        (output/"analysis.private.json").write_text(json.dumps(result["config"],indent=2),encoding="utf-8")
        audit={"configuration":result["config"],"query_rows":result["query_rows"],"measurements":result["measurements"],"sections":[]}
        with duckdb.connect() as con:
            for name,raw in result["raw"].items():
                if raw.empty:continue
                con.register("raw",raw);con.execute("COPY raw TO ? (FORMAT PARQUET)",[str(output/("input-"+name+".parquet"))])
            for section in result["sections"]:
                record={k:v for k,v in section.items() if k not in {"views","calculated_table"}};record["views"]={}
                for mode,view in section["views"].items():
                    record["views"][mode]={k:v for k,v in view.items() if k!="table"}
                    if view["status"]=="available":
                        con.register("view",view["table"]);con.execute("COPY view TO ? (FORMAT PARQUET)",[str(output/(section["section"]["id"]+"-"+mode.lower().replace(" ","-")+".parquet"))])
                        record["views"][mode].update(rows=len(view["table"]),comparison_status=view["table"].comparison_status.value_counts().to_dict())
                audit["sections"].append(record)
        from .analytics_pdf import export_analysis_pdf
        export_analysis_pdf(result,output/"analysis.pdf")
        (output/"audit.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
        (output/"complete.json").write_text(json.dumps({"processing_complete":True,"all_sections_available":all(s["status"]=="complete" for s in result["sections"])}),encoding="utf-8")
    except Exception:
        (output/"INCOMPLETE.txt").write_text("Export failed; do not use partial output.",encoding="utf-8");raise
    return output
