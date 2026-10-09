"""Analytical charts and a self-contained, lazily rendered report workspace."""
from __future__ import annotations

import html
import json
import numpy as np
import pandas as pd
from bokeh.embed import json_item
from bokeh.layouts import column,row,gridplot
from bokeh.models import (Div,ColumnDataSource,DataTable,TableColumn,HoverTool,LinearColorMapper,ColorBar,Range1d)
from bokeh.palettes import Viridis256,RdBu11
from bokeh.plotting import figure
from bokeh.resources import INLINE

from .plotting import build_charts,color_for
from .analytics import time_group


def heatmaps(table,plot):
    charts=[]
    keys=["scenario","object_name","property_name","unit","model_name"]
    finite=table.value[np.isfinite(table.value)]
    low=float(finite.min()) if len(finite) else 0;high=float(finite.max()) if len(finite) else 1
    diverging=plot["comparison"] in {"Difference","Percent change"} or low<0<high
    if diverging:low,high=-max(abs(low),abs(high),1e-12),max(abs(low),abs(high),1e-12)
    elif low==high:high=low+1
    mapper=LinearColorMapper(palette=list(RdBu11[::-1]) if diverging else Viridis256,low=low,high=high,nan_color="#E5E7EB")
    for identity,group in list(table.groupby(keys,dropna=False,observed=True,sort=False))[:120]:
        data=group.copy();data["hours"]=(data.end_date-data.start_date).dt.total_seconds()/3600
        # Custom heatmaps on an interval recipe may contain subhourly observations.
        if data.start_date.dt.floor("h").duplicated().any() or data.hours.ne(1).any():
            data=time_group(data,"calendar-hour","mean")
        data["day"]=data.start_date.dt.strftime("%Y-%m-%d");data["clock"]=data.start_date.dt.hour.astype(str)
        days=pd.date_range(data.start_date.min().normalize(),data.start_date.max().normalize()).strftime("%Y-%m-%d").tolist();ticks=days[::max(1,len(days)//24)]
        chart=figure(title=f"{identity[0]} | {identity[1]} | {identity[3]}",x_range=[str(h) for h in range(24)],y_range=days[::-1],width=650,height=550,
            tools="pan,wheel_zoom,box_zoom,reset,save")
        source=ColumnDataSource(data)
        chart.rect(x="clock",y="day",width=1,height=1,source=source,line_color=None,fill_color={"field":"value","transform":mapper})
        chart.yaxis.major_label_overrides={d:d if d in ticks else "" for d in days};chart.xaxis.axis_label="Hour of day"
        chart.yaxis.axis_label="Reported date";chart.add_layout(ColorBar(color_mapper=mapper,title=plot["comparison"]),"right")
        chart.add_tools(HoverTool(tooltips=[("Case","@scenario"),("Object","@object_name"),("Date","@day"),("Hour","@clock"),("Value","@value{0,0.000}"),("Status","@comparison_status")]))
        charts.append(chart)
    return gridplot(charts,ncols=plot["columns"],sizing_mode="stretch_width",merge_tools=False)


def scatters(table,plot):
    charts=[]
    for (obj,unit),group in table.groupby(["object_name","unit"],observed=True,dropna=False,sort=False):
        chart=figure(title=str(obj),width=600,height=450,tools="pan,wheel_zoom,box_zoom,reset,save")
        for case,data in group.groupby("scenario",observed=True,sort=False):
            data=data.copy();data["stamp"]=data.start_date.astype(str)
            chart.scatter(x="metric_x",y="value",source=ColumnDataSource(data),legend_label=str(case),color=color_for(case,plot["colors"]),size=4,alpha=.45)
        chart.xaxis.axis_label="Load (GW)";chart.yaxis.axis_label=f"Price ({unit})";chart.legend.click_policy="hide"
        legend=chart.legend[0];chart.add_layout(legend,"below")
        chart.add_tools(HoverTool(tooltips=[("Case","@scenario"),("Timestamp","@stamp"),("Load (GW)","@metric_x{0,0.000}"),("Price","@value{0,0.000}"),("Model","@model_name")]))
        charts.append(chart)
    return gridplot(charts,ncols=plot["columns"],sizing_mode="stretch_width",merge_tools=False)


def section_layout(result,scenarios=None,*,table_preview=True):
    diagnostics=result["diagnostics"]
    incomplete=sum(c.get("series_with_incomplete_window",0) for c in diagnostics.get("input_coverage",{}).values())
    heading=Div(text=f"<h2>{html.escape(result['section']['title'])}</h2><p>{html.escape(result['definition']['note'])}</p>"
        f"<p>Coverage: {html.escape(result['status'])}. Undefined metric rows: {diagnostics.get('undefined_metric_rows',0):,}. "
        f"Partial monthly rows: {diagnostics.get('partial_month_rows',0):,}. Input series with incomplete selected-window coverage: {incomplete:,}.</p>"
        +(f"<p>{html.escape(result['reason'])}</p>" if result.get("reason") else ""))
    views=[];preview=None
    for mode,view in result["views"].items():
        if view["status"]!="available":
            views.append(column(Div(text=f"<h3>{html.escape(mode)}</h3><p>{html.escape(view['reason'])}</p>"),sizing_mode="stretch_width"));continue
        data=view["table"]
        if scenarios:data=data[data.scenario.isin(scenarios)]
        if data.empty:views.append(column(Div(text=f"<h3>{mode}</h3><p>No matching display cases.</p>")));continue
        if preview is None:preview=data
        plot=view["plot"]
        try:
            if plot["chart_type"]=="Heatmap":chart=heatmaps(data,plot);notes=[]
            elif plot["chart_type"]=="Scatter":chart=scatters(data,plot);notes=[]
            else:chart,notes=build_charts(data,plot)
            missing=int((~data.comparison_status.isin(["absolute","matched"])).sum())
            views.append(column(Div(text=f"<h3>{html.escape(mode)}</h3><p>{missing:,} missing or undefined comparisons. {html.escape(' '.join(notes))}</p>"),chart,sizing_mode="stretch_width"))
        except Exception as exc:views.append(column(Div(text="Cannot draw: "+html.escape(str(exc)))))
    children=[heading,row(*views,sizing_mode="stretch_width") if views else Div(text="No usable reported inputs for this recipe.")]
    if table_preview and preview is not None:
        fields=[c for c in ("scenario","year","start_date","category_name","object_name","property_name","unit","metric_x","exceedance","value","absolute_value","baseline_value","comparison_status") if c in preview]
        data=preview[fields].head(500).copy()
        if "start_date" in data:data["start_date"]=data.start_date.astype(str)
        children.extend([Div(text="Table previews the first 500 rows of the first view. Complete values are exported to Parquet."),
            DataTable(source=ColumnDataSource(data),columns=[TableColumn(field=c,title=c) for c in fields],height=250,sizing_mode="stretch_width")])
    return column(*children,sizing_mode="stretch_width")


def offline_analysis_document(result):
    config=result["config"]
    items=[json_item(section_layout(section,table_preview=False),"chart-root") for section in result["sections"]]
    script_json=lambda value:json.dumps(value).replace("<","\\u003c")
    options="".join(f'<option value="{i}">{html.escape(r["section"]["title"])}</option>' for i,r in enumerate(result["sections"]))
    checks="; ".join(r["section"]["title"]+": "+r["status"] for r in result["sections"])
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(config["title"])}</title>
<style>body{{font:14px Arial,sans-serif;margin:20px;color:#111827}}select{{padding:8px;min-width:300px}}iframe{{border:0;width:100%;height:1000px}}details{{margin:12px 0}}label{{display:block;margin:8px 0}}</style></head><body>
<h1>{html.escape(config["title"])}</h1><p>Baseline: {html.escape(config["baseline"])}; {len(config["selected_sources"])} cases; {result["query_rows"]:,} unique queried rows.</p>
<p>Interval window: {html.escape(config["date_from"])} through {html.escape(config["date_to"])}. Annual recipes use their configured annual bounds.</p>
<p>Offline charts retain the selected data and baseline. Reopen the configuration in the live viewer to change queries or report settings.</p>
<details><summary>All section coverage</summary><p>{html.escape(checks)}</p></details>
<label for="analysis-section">Report section</label><select id="analysis-section">{options}</select>
<iframe id="analysis-view" title="Selected analysis charts"></iframe>
<script type="application/json" id="analysis-data">{script_json(items)}</script>
<script>
const sections=JSON.parse(document.getElementById("analysis-data").textContent);
const resources={script_json(INLINE.render())};const frame=document.getElementById("analysis-view");
frame.addEventListener("load",()=>{{const root=frame.contentDocument.getElementById("chart-root");if(!root)return;
const resize=()=>frame.style.height=Math.max(1000,root.getBoundingClientRect().height+40)+"px";new frame.contentWindow.ResizeObserver(resize).observe(root);resize();}});
function display(index){{frame.style.height="1000px";const data=JSON.stringify(sections[index]).replaceAll("<","\\\\u003c");
frame.srcdoc='<!doctype html><html><head><meta charset="utf-8">'+resources+'</head><body style="margin:0"><div id="chart-root"></div><script>Bokeh.embed.embed_item('+data+',"chart-root");<\\/script></body></html>';}}
document.getElementById("analysis-section").addEventListener("change",e=>display(Number(e.target.value)));display(0);
</script></body></html>'''
