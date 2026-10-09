"""Vector analytical report companion with section bookmarks and full facets."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import landscape,A4
from reportlab.lib.colors import HexColor
from bokeh.palettes import Viridis256,RdBu11

from .bundle_pdf import _chart,_text
from .plotting import color_for


def _scatter(pdf,table,plot,rect):
    x,y,w,h=rect
    good=table[np.isfinite(table.value)&np.isfinite(table.metric_x)]
    if good.empty:return []
    lo,hi=float(good.metric_x.min()),float(good.metric_x.max());bottom,top=float(good.value.min()),float(good.value.max())
    dx=hi-lo or 1;dy=top-bottom or 1;lo-=dx*.04;hi+=dx*.04;bottom-=dy*.04;top+=dy*.04
    pdf.setStrokeColor(HexColor("#D1D5DB"));pdf.rect(x,y,w,h,fill=0,stroke=1)
    pdf.setFont("Helvetica",7)
    for i in range(5):
        xv=lo+(hi-lo)*i/4;yv=bottom+(top-bottom)*i/4
        pdf.setStrokeColor(HexColor("#E5E7EB"));pdf.line(x,y+i*h/4,x+w,y+i*h/4)
        pdf.setFillColor(HexColor("#374151"));pdf.drawRightString(x-5,y+i*h/4-2,f"{yv:.3g}")
        pdf.drawCentredString(x+i*w/4,y-12,f"{xv:.3g}")
    legend=[]
    for case,group in good.groupby("scenario",observed=True,sort=False):
        color=color_for(case,plot["colors"]);legend.append((case,color));pdf.setFillColor(HexColor(color))
        for row in group.itertuples():pdf.circle(x+(row.metric_x-lo)/(hi-lo)*w,y+(row.value-bottom)/(top-bottom)*h,1.2,fill=1,stroke=0)
    pdf.setFillColor(HexColor("#374151"));pdf.setFont("Helvetica",8)
    pdf.drawString(x,y-27,"Load (GW)");pdf.drawString(x,y+h+5,"Price ($/MWh)")
    return legend


def _heatmap(pdf,table,plot,rect,low,high):
    x,y,w,h=rect;data=table.copy();data["day"]=data.start_date.dt.strftime("%Y-%m-%d");data["hour"]=data.start_date.dt.hour
    days=pd.date_range(data.start_date.min().normalize(),data.start_date.max().normalize()).strftime("%Y-%m-%d").tolist()
    palette=list(RdBu11[::-1]) if plot["comparison"] in {"Difference","Percent change"} or low<0<high else list(Viridis256)
    if low==high:high=low+1
    for row in data.itertuples():
        if not math.isfinite(row.value):continue
        idx=min(len(palette)-1,max(0,int((row.value-low)/(high-low)*(len(palette)-1))))
        pdf.setFillColor(HexColor(palette[idx]));pdf.rect(x+row.hour*w/24,y+(len(days)-days.index(row.day)-1)*h/len(days),w/24+.05,h/len(days)+.05,fill=1,stroke=0)
    pdf.setFillColor(HexColor("#374151"));pdf.setFont("Helvetica",7)
    for hour in [0,6,12,18,23]:pdf.drawCentredString(x+(hour+.5)*w/24,y-12,str(hour))
    for idx in range(0,len(days),max(1,len(days)//8)):pdf.drawRightString(x-4,y+(len(days)-idx-.5)*h/len(days),days[idx][5:])
    pdf.drawString(x,y-26,f"Hour of day | {table.unit.iloc[0]} | scale {low:.4g} to {high:.4g}")
    for index,color in enumerate(palette):
        pdf.setFillColor(HexColor(color));pdf.rect(x+index*w/len(palette),y-43,w/len(palette)+.02,8,fill=1,stroke=0)
    return []


def export_analysis_pdf(result,path):
    pdf=canvas.Canvas(str(path),pagesize=landscape(A4));width,height=landscape(A4);page=0
    pdf.setTitle(result["config"]["title"])
    def footer():
        nonlocal page
        page+=1;pdf.setFillColor(HexColor("#64748B"));pdf.setFont("Helvetica",8)
        pdf.drawString(30,23,"Queries, units, calculations, coverage, and complete values are in audit.json and the companion Parquets.")
        pdf.drawRightString(width-30,23,str(page));pdf.showPage()
    def heading(title,note):
        pdf.setFillColor(HexColor("#111827"));pdf.setFont("Helvetica-Bold",17);pdf.drawString(30,height-40,title[:83])
        return _text(pdf,note,30,height-62,width=125,size=9)-10
    config=result["config"]
    y=heading(config["title"],f"Baseline: {config['baseline']}. {len(config['selected_sources'])} cases. Interval dates: {config['date_from']} through {config['date_to']}. Annual reports use their configured annual years.")
    for section in result["sections"]:
        if y<75:footer();y=heading("Report coverage, continued","Complete details are in the audit and offline HTML.")
        y=_text(pdf,f"{section['section']['title']}: {section['status']}",30,y,width=125,size=9)
    footer()
    for section in result["sections"]:
        views={k:v for k,v in section["views"].items() if v["status"]=="available"}
        pdf.bookmarkPage(section["section"]["id"]);pdf.addOutlineEntry(section["section"]["title"],section["section"]["id"],level=0,closed=False)
        if not views:
            heading(section["section"]["title"],section.get("reason","No usable reported inputs"));footer();continue
        plot=section["plot"];facet=plot["facet"]
        tables=[v["table"] for v in views.values()]
        if plot["chart_type"]=="Heatmap":
            choices=list(dict.fromkeys(tuple(row) for t in tables for row in t[["scenario","object_name"]].drop_duplicates().itertuples(index=False,name=None)))
        else:
            if plot["chart_type"] in {"Stacked Bar","Stacked Area"} and facet=="None" and plot["series"]!="scenario":facet="scenario"
            choices=list(dict.fromkeys(x for t in tables for x in t[facet])) if facet!="None" else [None]
        limits={}
        if plot["shared_axes"]:
            for mode,view in views.items():
                t=view["table"]
                if t.unit.nunique()!=1:continue
                if plot["chart_type"] in {"Stacked Bar","Stacked Area"}:
                    keys=list(dict.fromkeys(([facet] if facet!="None" else [])+[plot["x"]]))
                    pos=t.assign(p=t.value.clip(lower=0)).groupby(keys,observed=True).p.sum();neg=t.assign(n=t.value.clip(upper=0)).groupby(keys,observed=True).n.sum()
                    limits[mode]=(min(0,float(neg.min())),max(0,float(pos.max())))
                else:
                    finite=t.value[np.isfinite(t.value)]
                    if len(finite):
                        low,high=float(finite.min()),float(finite.max())
                        if plot["chart_type"]=="Heatmap" and (mode in {"Difference","Percent change"} or low<0<high):low,high=-max(abs(low),abs(high),1e-12),max(abs(low),abs(high),1e-12)
                        limits[mode]=(min(0,low),max(0,high)) if plot["chart_type"]=="Bar" else (low,high)
        for choice in choices:
            months=sorted(set(x for t in tables for x in t.start_date.dt.strftime("%Y-%m"))) if plot["chart_type"]=="Heatmap" else [None]
            for month in months:
                modes=list(views)
                for offset in range(0,len(modes),2):
                    heading(section["section"]["title"],f"{facet}: {choice}. Baseline: {config['baseline']}."+(f" Calendar month: {month}." if month else ""))
                    _text(pdf,section["definition"]["note"],30,height-88,width=175,size=7)
                    legends=[]
                    for index,mode in enumerate(modes[offset:offset+2]):
                        view=views[mode];table=view["table"]
                        if plot["chart_type"]=="Heatmap":table=table[(table.scenario==choice[0])&(table.object_name==choice[1])&table.start_date.dt.strftime("%Y-%m").eq(month)]
                        elif choice is not None:table=table[table[facet]==choice]
                        rect=(80+index*width/2,245,width/2-115,220)
                        if len(modes)==1:rect=(80,245,width-130,220)
                        if table.empty:continue
                        if plot["chart_type"]=="Heatmap":
                            low,high=limits.get(mode,(float(table.value.min()),float(table.value.max())))
                            if not math.isfinite(low) or not math.isfinite(high):low,high=0,1
                            _heatmap(pdf,table,view["plot"],rect,low,high)
                        elif plot["chart_type"]=="Scatter":legends.extend(_scatter(pdf,table,view["plot"],rect))
                        else:legends.extend(_chart(pdf,table,view["plot"],rect,"",limits.get(mode)))
                        pdf.setFillColor(HexColor("#111827"));pdf.setFont("Helvetica-Bold",11);pdf.drawString(rect[0],485,mode)
                    unique=list(dict.fromkeys(legends))
                    if len(unique)>32:
                        pdf.setFont("Helvetica",7);pdf.drawString(30,194,f"First 32 of {len(unique)} legend entries; full legends are in the HTML companion.")
                    for index,(label,color) in enumerate(unique[:32]):
                        xx=30+(index%4)*(width-60)/4;yy=183-(index//4)*15
                        pdf.setFillColor(HexColor(color));pdf.rect(xx,yy,8,8,fill=1,stroke=0);pdf.setFillColor(HexColor("#374151"));pdf.setFont("Helvetica",7);pdf.drawString(xx+12,yy+1,str(label)[:27])
                    undefined=section["diagnostics"].get("undefined_metric_rows",0);partial=section["diagnostics"].get("partial_month_rows",0)
                    _text(pdf,f"Coverage: {section['status']}. Undefined metric rows: {undefined}. Partial monthly rows: {partial}. Absolute/difference scales may differ. See the audit for input gaps and unavailable views.",30,53,width=145,size=7)
                    footer()
    pdf.save()
