"""Printable vector companion to annual comparison bundles."""
from __future__ import annotations

import math
import textwrap

import numpy as np
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, A4

from .plotting import color_for


def _text(pdf, text, x, y, width=95, size=9):
    pdf.setFont("Helvetica", size)
    for line in textwrap.wrap(str(text).replace("—", "-").replace("–", "-"), width):
        pdf.drawString(x, y, line)
        y -= size + 3
    return y


def _chart(pdf, table, plot, rect, title, limits=None):
    x, y, width, height = rect
    series = plot["series"]
    stacked = plot["chart_type"] in {"Stacked Bar", "Stacked Area"}
    pdf.setFillColor(HexColor("#111827")); pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(x, y+height+18, title)
    if table.empty:
        _text(pdf, "No measurements for this selection.", x, y+height-10)
        return []
    series_keys = list(dict.fromkeys([series] + (["scenario"] if plot["facet"] != "scenario" and series != "scenario" else [])))
    groups = list(table.groupby(series_keys, sort=False, dropna=False))
    order = {name:i for i,name in enumerate(plot["series_order"])}
    groups.sort(key=lambda pair:(order.get(str(pair[0][0] if isinstance(pair[0],tuple) else pair[0]),9999),str(pair[0])))
    years = sorted(set(table.year))
    values = [g.set_index("year").reindex(years).value.to_numpy(dtype=float) for _,g in groups]
    complete = np.all(np.isfinite(values),axis=0)
    positive = np.sum([np.where(v>0,v,0) for v in values],axis=0)
    negative = np.sum([np.where(v<0,v,0) for v in values],axis=0)
    finite = np.concatenate([positive,negative]) if stacked else table.value.dropna().to_numpy()
    low, high = min(0,float(np.nanmin(finite))) if len(finite) else 0, max(0,float(np.nanmax(finite))) if len(finite) else 1
    if limits is not None:
        low,high=limits
    if high==low:high=low+1
    span=high-low
    if low<0:low-=span*.04
    if high>0:high+=span*.04
    span=high-low
    px=lambda index:x+(index+.5)*width/len(years)
    py=lambda value:y+(value-low)/span*height
    pdf.setLineWidth(.5)
    ticks=[low+span*tick/4 for tick in range(5)]
    ticks=sorted([value for value in ticks if abs(value)>span*.08]+[0.0])
    for value in ticks:
        pdf.setStrokeColor(HexColor("#D1D5DB"));pdf.line(x,py(value),x+width,py(value))
        pdf.setFillColor(HexColor("#374151"));pdf.setFont("Helvetica",7)
        pdf.drawRightString(x-5,py(value)-2,f"{value:,.3g}")
    pos,neg=np.zeros(len(years)),np.zeros(len(years))
    legend=[]
    for (label,_),vals in zip(groups,values):
        parts=label if isinstance(label,tuple) else (label,)
        color=color_for(str(parts[0]),plot["colors"])
        legend.append((" | ".join(map(str,parts)),color))
        pdf.setStrokeColor(HexColor(color));pdf.setFillColor(HexColor(color))
        if stacked:
            for index,val in enumerate(vals):
                if not complete[index]:continue
                base=pos[index] if val>=0 else neg[index]
                if plot["chart_type"] == "Stacked Area" and index+1<len(vals) and complete[index+1]:
                    nxt=vals[index+1]
                    nxtbase=pos[index+1] if nxt>=0 else neg[index+1]
                    path=pdf.beginPath();path.moveTo(px(index),py(base));path.lineTo(px(index),py(base+val))
                    path.lineTo(px(index+1),py(nxtbase+nxt));path.lineTo(px(index+1),py(nxtbase));path.close()
                    pdf.drawPath(path,fill=1,stroke=0)
                elif plot["chart_type"] == "Stacked Bar":
                    pdf.rect(px(index)-width/len(years)*.4,py(min(base,base+val)),width/len(years)*.8,abs(val)/span*height,fill=1,stroke=0)
            pos+=np.where(vals>0,vals,0);neg+=np.where(vals<0,vals,0)
        else:
            previous=None;pdf.setLineWidth(1.3)
            for index,val in enumerate(vals):
                if not math.isfinite(val):previous=None;continue
                coords=(px(index),py(val))
                if plot["chart_type"] == "Bar":
                    offset=(len(legend)-1-(len(groups)-1)/2)*width/len(years)*.8/len(groups)
                    pdf.rect(coords[0]+offset-width/len(years)*.4/len(groups),py(min(0,val)),width/len(years)*.8/len(groups),abs(val)/span*height,fill=1,stroke=0)
                else:
                    if previous and plot["chart_type"] in {"Line","Dot-Line"}:pdf.line(*previous,*coords)
                    if plot["chart_type"] in {"Dot","Dot-Line"} or len(vals)==1:pdf.circle(*coords,2,fill=1,stroke=0)
                previous=coords
    if stacked and plot["net_total"]:
        pdf.setFillColor(HexColor("#222222"))
        for index,value in enumerate(np.sum(np.nan_to_num(values),axis=0)):
            if complete[index]:pdf.circle(px(index),py(value),2.5,fill=1,stroke=0)
        legend.append(("Net total","#222222"))
    pdf.setFillColor(HexColor("#374151"));pdf.setFont("Helvetica",7)
    for index,year in enumerate(years):
        if index%max(1,len(years)//8)==0 or index==len(years)-1:pdf.drawCentredString(px(index),y-12,str(year))
    unit="%" if plot["comparison"]=="Percent change" else "ratio" if plot["comparison"]=="Ratio" else str(table.unit.iloc[0])
    pdf.setFont("Helvetica",8);pdf.drawString(x,y-27,unit)
    if (~complete).any() and stacked:
        pdf.drawString(x,y-40,f"{int((~complete).sum())} incomplete stack positions omitted")
    return legend


def export_bundle_pdf(bundle,path):
    pdf=canvas.Canvas(str(path),pagesize=landscape(A4));width,height=landscape(A4)
    pdf.setTitle(bundle["config"]["title"])
    page=0
    def footer():
        nonlocal page
        page+=1;pdf.setFillColor(HexColor("#64748B"));pdf.setFont("Helvetica",8)
        pdf.drawString(35,23,"Values, queries, units and source coverage are recorded in audit.json and the companion Parquets.")
        pdf.drawRightString(width-35,23,str(page));pdf.showPage()
    pdf.setFillColor(HexColor("#111827"));pdf.setFont("Helvetica-Bold",23)
    pdf.drawString(35,height-55,bundle["config"]["title"][:70])
    y=_text(pdf,f"Shared baseline: {bundle['config']['baseline']}. {len(bundle['config']['selected_sources'])} selected solutions. Annual reported measurements; no inferred cost decomposition or discounting.",35,height-82,width=115,size=10)-15
    for result in bundle["sections"]:
        y=_text(pdf,f"{result['section']['title']}: {result['status']}",35,y,width=100,size=10)
    _text(pdf,"Each report preserves its measurement units. Emission and region objects remain separate. Missing data is not zero. Absolute values and differences share a baseline but have separate Y scales.",35,y-15,width=115,size=10)
    footer()
    for result in bundle["sections"]:
        available={mode:view for mode,view in result["views"].items() if view["status"]=="available"}
        if not available:
            pdf.setFillColor(HexColor("#111827"));pdf.setFont("Helvetica-Bold",17);pdf.drawString(35,height-45,result["section"]["title"][:75])
            _text(pdf,"Unavailable: "+result.get("reason","no usable reported annual measurements"),35,height-80,width=110)
            footer();continue
        plot=result["plot"]
        facet=plot["facet"]
        if facet=="None" and plot["chart_type"] in {"Stacked Bar","Stacked Area"} and plot["series"]!="scenario":facet="scenario"
        choices=list(dict.fromkeys(v for view in available.values() for v in view["table"][facet].tolist())) if facet!="None" else [None]
        modes=list(available)
        limits={}
        if plot["shared_axes"]:
            for mode,view in available.items():
                table=view["table"]
                if table.unit.nunique()!=1:continue
                if plot["chart_type"] in {"Stacked Bar","Stacked Area"}:
                    keys=list(dict.fromkeys(([facet] if facet!="None" else [])+["year"]))
                    pos=table.assign(_positive=table.value.clip(lower=0)).groupby(keys)._positive.sum()
                    neg=table.assign(_negative=table.value.clip(upper=0)).groupby(keys)._negative.sum()
                    limits[mode]=(min(0,float(neg.min())),max(0,float(pos.max())))
                else:
                    finite=table.value[np.isfinite(table.value)]
                    if not finite.empty:limits[mode]=(min(0,float(finite.min())),max(0,float(finite.max())))
        for choice in choices:
            for start in range(0,len(modes),2):
                pdf.setFillColor(HexColor("#111827"));pdf.setFont("Helvetica-Bold",16)
                pdf.drawString(35,height-43,result["section"]["title"][:80])
                _text(pdf,f"{facet}: {choice} | Baseline: {bundle['config']['baseline']}",35,height-62,width=115,size=9)
                _text(pdf,result["definition"]["note"] or "Annual values, grouped by the configured reporting dimension.",35,height-79,width=115,size=8)
                legends=[]
                for index,mode in enumerate(modes[start:start+2]):
                    view=available[mode];table=view["table"]
                    if choice is not None:table=table[table[facet]==choice]
                    legend=_chart(pdf,table,view["plot"],(75+index*width/2,230,width/2-105,240),mode,limits.get(mode))
                    legends.extend(legend)
                # A common, wrapped legend leaves the chart area unobstructed.
                unique=list(dict.fromkeys(legends))
                for index,(label,color) in enumerate(unique[:32]):
                    col=index%4;row=index//4;xx=35+col*(width-70)/4;yy=188-row*16
                    pdf.setFillColor(HexColor(color));pdf.rect(xx,yy,9,9,fill=1,stroke=0)
                    pdf.setFillColor(HexColor("#374151"));pdf.setFont("Helvetica",7)
                    pdf.drawString(xx+13,yy+1,label[:27])
                if len(unique)>32:_text(pdf,f"Legend shows first 32 of {len(unique)} series; full labels are available in HTML.",35,59,width=125,size=7)
                unavailable=[mode+": "+view.get("reason", "unavailable") for mode,view in result["views"].items() if view["status"]!="available"]
                missing=[c["scenario"]+": "+c["status"] for c in result["coverage"] if c["status"]!="available"]
                if missing or unavailable:_text(pdf,"Coverage: "+"; ".join(missing+unavailable),35,66,width=125,size=7)
                footer()
    pdf.save()
