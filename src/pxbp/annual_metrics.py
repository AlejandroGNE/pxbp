"""Annual report definitions, unit checks, and portable multi-property dashboards."""
from __future__ import annotations

import html
import json
import math
import tempfile
from pathlib import Path

import pandas as pd

from .reports import TECHNOLOGY_COLORS
from .sources import Selection, stream_query

COLORS = {**TECHNOLOGY_COLORS, "Other": "#9AA6B2", "Flowgate": "#64748B",
          "Gas infrastructure": "#A96235", "System/zone": "#187F94", "Line": "#106BA7", "Constraint": "#64748B",
          "Oil": "#D55E00", "Gas-Other": "#9570AD", "Demand response": "#777777"}
FACTORS = {"power": {"MW": .001, "GW": 1, "kW": .000001},
           "energy": {"MWh": .000001, "GWh": .001, "TWh": 1},
           "money": {"$": 1e-9, "$000": 1e-6, "k$": 1e-6, "$M": .001, "M$": .001, "$B": 1},
           "count": {"-": 1, "": 1, "units": 1, "Units": 1},
           "percent": {"%": 1}, "hours": {"h": 1, "hrs": 1, "hours": 1},
           "native": None}
DISPLAY_UNITS = {"power": "GW", "energy": "TWh", "money": "$B", "count": "units", "percent": "%", "hours": "hours"}
GEOGRAPHY_LABELS = {"planning_region": "Planning region", "owner": "Transmission owner", "state": "State",
                    "technology": "Technology (system total)", "object_name": "Asset / flowgate"}
SNAPSHOT_PROPERTIES = {"installedcapacity", "generationcapacity", "firmgenerationcapacity", "firmcapacity",
                       "capacityreservemargin", "maxcapacityreservemargin", "mincapacityreservemargin",
                       "capacityfactor", "peakload", "planningpeakload", "loading", "exportlimit", "importlimit",
                       "price", "shadowprice", "capacityprice"}


def validate_metrics_spec(spec):
    if not isinstance(spec, dict) or not spec.get("metrics") or not isinstance(spec.get("assets"), list):
        raise ValueError("Annual report needs metrics and assets")
    ids = set()
    for metric in spec["metrics"]:
        if metric["id"] in ids:
            raise ValueError("Duplicate metric id")
        ids.add(metric["id"])
        if metric.get("family") not in FACTORS or metric.get("temporal") not in ("sum", "snapshot"):
            raise ValueError("Metric needs a unit family and sum/snapshot temporal rule")
        if not metric.get("queries"):
            raise ValueError("Metric needs queries")
        if metric.get("object_label") not in (None, "mapped"):
            raise ValueError("object_label must be mapped or omitted")
        if metric.get("geographies") is not None and (not isinstance(metric["geographies"], list) or not metric["geographies"] or set(metric["geographies"]) - GEOGRAPHY_LABELS.keys()):
            raise ValueError("Choose supported report geographies")
        collections = set()
        for query in metric["queries"]:
            Selection(query)
            if not isinstance(query["properties"], str) or not query["properties"].strip():
                raise ValueError("Each metric query needs one named property")
            collection = query["collection"].removeprefix("System")
            if collection in collections:
                raise ValueError("Use one property per collection in a metric; report cost components separately")
            collections.add(collection)
            if query.get("period") != "Year" or query.get("aggregate_by") or query.get("aggregate_type"):
                raise ValueError("Annual metrics require individual asset Year queries")
            prop = str(query["properties"]).replace(" ", "").lower()
            if prop in SNAPSHOT_PROPERTIES and metric["temporal"] != "snapshot":
                raise ValueError("Stock, ratio and price properties require snapshot temporal rules")
    identities = [(a["collection"].removeprefix("System"), a["object_name"]) for a in spec["assets"]]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate annual asset mapping")
    if any(a.get("technology", "Other") not in COLORS for a in spec["assets"]):
        raise ValueError("Unsupported technology color identity")
    return spec


def metric_rows(frame, spec, metric):
    """Validate dimensions before joining explicit geography and converting units."""
    values = frame.copy()
    values["year"] = pd.to_datetime(values["start_date"], format="mixed").dt.year
    if spec.get("years"):
        values = values[values.year.isin(spec["years"])].copy()
    if values.empty:
        return pd.DataFrame()
    values["collection"] = values.collection_name.str.removeprefix("System")
    allowed = {(q["collection"].removeprefix("System"), q["properties"]) for q in metric["queries"]}
    identities = pd.MultiIndex.from_frame(values[["collection", "property_name"]])
    if not identities.isin(allowed).all() or not values.period_type_name.eq("Year").all():
        raise ValueError("Unexpected annual metric property or period")
    if values.duplicated(["scenario", "collection", "object_name", "year"]).any():
        raise ValueError("Multiple rows for one annual asset; narrow sample/band/model selections")
    dimensions = ["phase_name", "timeslice_name", "sample_name", "model_name", "band_id"]
    for name in dimensions:
        if name not in values:
            values[name] = ""
    if values.groupby(["scenario", "collection"])[dimensions].nunique(dropna=False).gt(1).any().any():
        raise ValueError("Mixed annual query dimensions")
    attributes = ["technology", "sector", "owner", "state", "planning_region", "mapping_status", "report_object_name", "related_asset"]
    mappings = pd.DataFrame(spec["assets"])
    if mappings.empty:
        mappings = pd.DataFrame(columns=["collection", "object_name", *attributes])
    mappings["collection"] = mappings.collection.str.removeprefix("System")
    for name in attributes:
        if name not in mappings:
            mappings[name] = None
    values = values.merge(mappings[["collection", "object_name", *attributes]], on=["collection", "object_name"], how="left", validate="many_to_one")
    values["sector"] = values.sector.fillna(values.collection.map(lambda c: "Generation" if c in ("Generators", "Batteries") else c))
    if metric.get("sectors"):
        values = values[values.sector.isin(metric["sectors"])].copy()
    if values.empty:
        return pd.DataFrame()
    values["source_object_name"] = values.object_name
    if metric.get("object_label") == "mapped":
        if values.report_object_name.isna().any() or values.report_object_name.eq("").any():
            raise ValueError("Mapped object label needs an explicit report_object_name")
        values["object_name"] = values.report_object_name
    values["reported_value"] = pd.to_numeric(values.value, errors="raise")
    if not values.reported_value.map(math.isfinite).all():
        raise ValueError("Annual metric value must be finite")
    prop = values.property_name.str.replace(" ", "", regex=False).str.lower()
    if (prop.isin({"installedcapacity", "generationcapacity", "capacitybuilt", "generationcapacitybuilt", "unitsbuilt"}) & values.reported_value.lt(-1e-8)).any():
        raise ValueError("Reported capacity and build quantities must be nonnegative")
    family = metric["family"]
    values["reported_unit"] = values.unit.astype(str)
    if family == "native":
        if values.reported_unit.nunique(dropna=False) != 1:
            raise ValueError("Native metric mixes units; split it into separate metrics")
        values["value"] = values.reported_value
    else:
        factors = values.reported_unit.map(FACTORS[family])
        if factors.isna().any():
            unit = values.loc[factors.isna(), "reported_unit"].iloc[0]
            raise ValueError(f"Unexpected {family} unit {unit!r} for {metric['id']}")
        values["value"] = values.reported_value * factors
        values["unit"] = DISPLAY_UNITS[family]
    for name, default in (("technology", "Other"), ("owner", "Unassigned"), ("state", "Unassigned"),
                          ("planning_region", "Unassigned"), ("mapping_status", "unmapped"), ("related_asset", "")):
        values[name] = values[name].fillna(default)
    values["metric"] = metric["id"]
    values["property"] = values.property_name
    return values[["metric", "scenario", "collection", "object_name", "source_object_name", "year", "technology", "sector",
                   "owner", "state", "planning_region", "value", "unit", "reported_value", "reported_unit", "mapping_status", "property", "related_asset"]]


def aggregate_metric(rows, metric, geography, year):
    if year == "All years":
        if metric["temporal"] == "snapshot":
            raise ValueError("Snapshot metrics require one year")
    else:
        rows = rows[rows.year == int(year)]
    if metric["family"] in ("percent", "native") and geography != "object_name":
        raise ValueError("Ratios and native-unit metrics must retain individual objects")
    return rows.groupby(["scenario", geography, "technology"], dropna=False, as_index=False).value.sum()


def collect_metrics(sources, spec, *, max_rows=1000000, timeout=600, audit_output=None):
    validate_metrics_spec(spec)
    results, coverage = {}, []
    for metric in spec["metrics"]:
        parts = []
        for query in metric["queries"]:
            frames = []
            selected_sources = []
            for source in sources:
                provenance_path = Path(source.path)/"import-provenance.json" if source.path else None
                if provenance_path and provenance_path.exists():
                    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                    choices = [c for c in provenance.get("coverage", []) if c["collection"] == query["collection"] and c["property"] == query["properties"]]
                    if choices and not any(c["status"] == "reported" for c in choices):
                        continue
                selected_sources.append(source)
            if selected_sources:
                for batch in stream_query(selected_sources, Selection(query, max_rows=max_rows, timeout=timeout)):
                    frames.append(batch.frame)
            frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            part = metric_rows(frame, spec, metric) if not frame.empty else pd.DataFrame()
            scope_counts = part.groupby(["scenario", "year"]).size().to_dict() if not part.empty else {}
            for source in sources:
                subset = frame[frame.scenario == source.label] if not frame.empty else frame
                reported_years = set(pd.to_datetime(subset.start_date).dt.year) if not subset.empty else set()
                for year in spec.get("years", sorted(reported_years)):
                    count = int(scope_counts.get((source.label, year), 0))
                    coverage.append({"metric": metric["id"], "scenario": source.label, "collection": query["collection"],
                                     "property": query["properties"], "year": year,
                                     "scope_rows": count,
                                     "status": "reported" if count else "no objects in report scope" if year in reported_years else "not reported"})
            if not part.empty:
                parts.append(part)
        values = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if not values.empty and values.unit.nunique(dropna=False) != 1:
            raise ValueError("Metric queries mix display units; split them into separate metrics")
        if not values.empty and audit_output is not None:
            import duckdb
            con = duckdb.connect()
            try:
                filename = f"metric-{len(results)+1:03d}.parquet"
                con.execute("COPY (SELECT * FROM values) TO ? (FORMAT PARQUET)", [str(Path(audit_output)/filename)])
            finally: con.close()
        if not values.empty and not metric.get("asset_detail") and metric["family"] not in ("percent", "native"):
            keys = ["metric", "scenario", "collection", "year", "technology", "sector", "owner", "state", "planning_region", "unit", "mapping_status"]
            values = values.groupby(keys, dropna=False, as_index=False).value.sum()
            values["object_name"] = "(group total)"
        results[metric["id"]] = values
    return results, coverage


def metrics_document(results, coverage, spec, scenarios):
    from bokeh.layouts import column, row
    from bokeh.models import ColumnDataSource, CustomJS, DataTable, Div, FactorRange, HoverTool, Select, TabPanel, TableColumn, Tabs, TextInput
    from bokeh.plotting import figure
    groups = {}
    years = list(map(str, spec["years"]))
    for metric in spec["metrics"]:
        groups.setdefault(metric.get("section", "Annual results"), []).append(metric)
    panels = []
    for section, metrics in groups.items():
        views, details = {}, {}
        active_colors = {tech: color for tech, color in COLORS.items() if any(not results[m["id"]].empty and tech in set(results[m["id"]].technology) for m in metrics)}
        for metric in metrics:
            values = results[metric["id"]]
            if values.empty:
                continue
            # Encode repeated labels once; keep full raw asset values in audit Parquet.
            fields = [k for k in ("scenario", "object_name", "source_object_name", "related_asset", "year", "value", "unit",
                      "technology", "owner", "state", "planning_region", "mapping_status") if k in values]
            detail_data, labels = {}, {}
            for field in fields:
                if field in ("year", "value"):
                    detail_data[field] = values[field].tolist()
                else:
                    encoded = pd.Categorical(values[field].fillna("").astype(str))
                    detail_data[field] = encoded.codes.tolist()
                    labels[field] = encoded.categories.tolist()
            details[metric["id"]] = {"data": detail_data, "labels": labels}
            geographies = ["object_name"] if metric["family"] in ("percent", "native") else metric.get("geographies", ["planning_region", "owner", "state", "technology"])
            metric_views = {}
            for geography in geographies:
                metric_views[geography] = {}
                for year in (["All years"] if metric["temporal"] == "sum" else []) + years:
                    # Grouping by technology is already the stack dimension.
                    group = values.assign(system="System") if geography == "technology" else values
                    field = "system" if geography == "technology" else geography
                    totals = aggregate_metric(group, metric, field, year)
                    metric_views[geography][year] = {}
                    for scenario in scenarios:
                        selected = totals[totals.scenario == scenario]
                        names = sorted(selected[field].unique())
                        lookup = selected.set_index([field, "technology"]).value.to_dict()
                        data = {"x": names}
                        for tech in active_colors:
                            data[tech] = [lookup.get((name, tech), 0) for name in names]
                        metric_views[geography][year][scenario] = data
            views[metric["id"]] = {"geographies": geographies, "years": (["All years"] if metric["temporal"] == "sum" else []) + years,
                                   "geography_options": [(g, GEOGRAPHY_LABELS.get(g, g)) for g in geographies],
                                   "unit": str(values.unit.iloc[0]), "title": metric["title"], "data": metric_views,
                                   "aliases": values.groupby("object_name").related_asset.first().fillna("").to_dict() if "related_asset" in values else {}}
        if not views:
            panels.append(TabPanel(title=section, child=Div(text="<p>No selected properties were reported. See coverage.</p>")))
            continue
        first = next(iter(views)); view = views[first]; geo = view["geographies"][0]; year = view["years"][-1] if metrics[0]["temporal"] == "snapshot" else view["years"][0]
        first_values = results[first]
        initial_case = next((s for s in scenarios if not first_values[(first_values.scenario == s) & (first_values.value.abs() > 1e-12)].empty), scenarios[0])
        initial_data = view["data"][geo][year][initial_case]
        if geo == "object_name":
            indices = sorted(range(len(initial_data["x"])), key=lambda i: sum(abs(initial_data[t][i]) for t in active_colors), reverse=True)[:20]
            initial_data = {key: [items[i] for i in indices] for key, items in initial_data.items()}
        source = ColumnDataSource(initial_data)
        chart = figure(x_range=FactorRange(*source.data["x"]), height=490, sizing_mode="stretch_width", title=view["title"], tools="pan,wheel_zoom,box_zoom,reset,save")
        chart.vbar_stack(list(active_colors), x="x", width=.8, color=list(active_colors.values()), legend_label=list(active_colors), source=source)
        chart.add_tools(HoverTool(tooltips=[("Group", "@x"), ("Technology", "$name"), ("Value", "@$name{0,0.000}")]))
        chart.yaxis.axis_label = view["unit"]; chart.xaxis.major_label_orientation = .9
        chart.legend.click_policy = "hide"; chart.add_layout(chart.legend[0], "right")
        metric_select = Select(title="Measure", value=first, options=[(k, v["title"]) for k, v in views.items()], sizing_mode="stretch_width")
        geo_select = Select(title="Group by", value=geo, options=view["geography_options"])
        year_select = Select(title="Year", value=year, options=view["years"])
        case_select = Select(title="Scenario", value=initial_case, options=scenarios, sizing_mode="stretch_width")
        detail_source = ColumnDataSource({})
        search = TextInput(title="Find an asset or flowgate", placeholder="Type part of an object name")
        table_fields = ("object_name", "year", "value", "unit", "source_object_name", "mapping_status") if view["geographies"] == ["object_name"] else ("object_name", "year", "value", "unit", "technology", "planning_region", "owner", "state", "mapping_status")
        if "related_asset" in first_values and first_values.related_asset.fillna("").ne("").any():
            table_fields = (*table_fields, "related_asset")
        table = DataTable(source=detail_source, columns=[TableColumn(field=k, title=k.replace("_", " ").title()) for k in table_fields],
                          height=430, sizing_mode="stretch_width", index_position=None)
        callback = CustomJS(args=dict(views=views, details=details, source=source, plot=chart, table_source=detail_source,
                metric=metric_select, geo=geo_select, year=year_select, scenario=case_select, search=search, axis=chart.yaxis[0]), code="""
            const v = views[metric.value];
            geo.options = v.geography_options; if (!v.geographies.includes(geo.value)) geo.value = v.geographies[0];
            year.options = v.years; if (!v.years.includes(year.value)) year.value = v.years[v.years.length-1];
            const data = v.data[geo.value][year.value][scenario.value];
            if (geo.value === 'object_name') {
                const stacks = Object.keys(data).filter(k=>k!=='x');
                const term = search.value.toLowerCase();
                const indices = data.x.map((_,i)=>i).filter(i=>data.x[i].toLowerCase().includes(term) || (v.aliases[data.x[i]] || '').toLowerCase().includes(term));
                indices.sort((a,b)=>stacks.reduce((s,k)=>s+Math.abs(data[k][b]),0)-stacks.reduce((s,k)=>s+Math.abs(data[k][a]),0));
                source.data = Object.fromEntries(Object.entries(data).map(([k,items])=>[k,indices.slice(0,20).map(i=>items[i])]));
            } else source.data = data;
            plot.x_range.factors = source.data.x;
            plot.title.text = v.title + ' — ' + year.value + (geo.value === 'object_name' ? ' — up to 20 objects' : ''); axis.axis_label = v.unit;
            source.change.emit();
            const encoded = details[metric.value], d = encoded.data;
            const decode = (k,i) => encoded.labels[k] ? encoded.labels[k][d[k][i]] : d[k][i];
            const filtered = Object.fromEntries(Object.keys(d).map(k=>[k,[]]));
            for (let i=0; i<d.value.length; i++) {
                if (decode('scenario',i) !== scenario.value || (year.value !== 'All years' && d.year[i] !== Number(year.value))) continue;
                const term = search.value.toLowerCase();
                if (!decode('object_name',i).toLowerCase().includes(term) && !(d.related_asset && decode('related_asset',i).toLowerCase().includes(term))) continue;
                for (const k of Object.keys(d)) filtered[k].push(decode(k,i));
            }
            table_source.data = filtered; table_source.change.emit();
        """)
        for control in (metric_select, geo_select, year_select, case_select, search):
            control.js_on_change("value", callback)
        # Initial table uses the same scenario/year selection as the chart.
        initial = first_values[list(details[first]["data"])]; initial = initial[initial.scenario == initial_case]
        if year != "All years": initial = initial[initial.year == int(year)]
        detail_source.data = ColumnDataSource.from_df(initial)
        panels.append(TabPanel(title=section, child=column(row(metric_select, case_select, sizing_mode="stretch_width"), row(geo_select, year_select),
            Div(text="<p>Object charts show up to 20 ranked matches. The table retains all matching annual records.</p>"), chart, search, table)))
    coverage_frame = pd.DataFrame(coverage)
    panels.append(TabPanel(title="Coverage", child=DataTable(source=ColumnDataSource(coverage_frame),
        columns=[TableColumn(field=k, title=k.title()) for k in coverage_frame.columns], height=650, sizing_mode="stretch_width")))
    methods = "<p>Installed capacity and ratios show one annual snapshot. Annual build, cost and energy measures can be summed over years. Ratios retain individual objects. Upfront build costs and annualized build costs are separate measures; they are never added to Total Cost. Unreported properties remain visible in coverage rather than becoming zero.</p><p>Owner and planning-region assignments use the current model. Unassigned geography and Other technology remain visible. Battery power is separate from storage energy. Constraint activity, binding hours and line congestion use reported annual summaries; these do not reconstruct hourly flow or a physical geographic map.</p>"
    panels.append(TabPanel(title="Methods", child=Div(text=methods + "<p>" + html.escape(spec.get("notes", "")) + "</p>")))
    return column(Div(text="<h1>" + html.escape(spec.get("title", "Annual solution reports")) + "</h1>"), Tabs(tabs=panels), sizing_mode="stretch_width")


def write_metrics_pdf(path, results, spec, scenarios):
    """Compact annual comparison pages; asset detail remains in HTML and audit Parquet."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.colors import HexColor
    from reportlab.lib.utils import simpleSplit
    width, height = landscape(A4); pdf = canvas.Canvas(str(path), pagesize=(width, height))
    pdf.setTitle(spec.get("title", "Annual solution reports"))
    for metric in spec["metrics"]:
        values = results[metric["id"]]
        pdf.setFillColor(HexColor("#182D40")); pdf.setFont("Helvetica-Bold", 16); pdf.drawString(35, height-35, metric["title"])
        if values.empty:
            pdf.setFont("Helvetica", 12); pdf.drawString(35,height-75,"Not reported in the selected sources."); pdf.showPage(); continue
        unit = str(values.unit.iloc[0])
        if metric.get("asset_detail") or metric["family"] in ("percent", "native"):
            selected = values[values.year == spec["years"][-1]] if metric["temporal"] == "snapshot" else values
            table = selected.groupby(["object_name", "scenario"]).value.sum().unstack("scenario")
            ranked = table.abs().max(axis=1).sort_values(ascending=False).head(20).index
            table = table.reindex(ranked)
            pdf.setFont("Helvetica", 10)
            subtitle = f"{unit} | {spec['years'][-1]} snapshot" if metric["temporal"] == "snapshot" else f"{unit} | {spec['years'][0]}-{spec['years'][-1]} summed per object"
            pdf.drawString(35,height-60,subtitle + " | up to 20 objects by largest absolute case value")
            for i,scenario in enumerate(scenarios):
                pdf.setFont("Helvetica",7);pdf.drawString(35,height-82-i*11,f"Case {i+1}: {scenario[:140]}")
            top=height-105-len(scenarios)*11; step=(width-330)/max(len(scenarios),1)
            pdf.setFont("Helvetica-Bold",9);pdf.drawString(35,top,"Object")
            for i in range(len(scenarios)):pdf.drawRightString(295+(i+1)*step,top,f"Case {i+1}")
            for idx,(name,item) in enumerate(table.iterrows()):
                y=top-20-idx*15;pdf.setFont("Helvetica",8);pdf.drawString(35,y,str(name)[:47])
                for i,scenario in enumerate(scenarios):
                    v=item.get(scenario,float('nan'));pdf.drawRightString(295+(i+1)*step,y,"missing" if pd.isna(v) else f"{v:,.3g}")
            pdf.setFont("Helvetica",8);pdf.drawString(35,32,"Objects are retained separately. Missing is not zero. Full annual asset detail is available in HTML and audit Parquet.")
            pdf.showPage(); continue
        totals = values.groupby(["scenario","year"],as_index=False).value.sum()
        lo = min(0,float(totals.value.min())); hi=max(0,float(totals.value.max())) or 1; span=hi-lo
        left,bottom,pw,ph=65,80,width-105,height-220
        pdf.setFont("Helvetica",10);pdf.drawString(35,height-60,f"Annual values | {unit} | {metric['temporal']} across years")
        for tick in range(6):
            y=bottom+ph*tick/5;pdf.setStrokeColor(HexColor('#D8DFE6'));pdf.line(left,y,left+pw,y)
            pdf.setFillColor(HexColor('#182D40'));pdf.drawRightString(left-8,y-3,f'{lo+span*tick/5:.3g}')
        years=spec['years']
        case_colors=['#187F94','#820000','#5E1688','#5B9844','#106BA7','#A96235','#FF4A88']
        for idx,scenario in enumerate(scenarios):
            color=case_colors[idx%len(case_colors)];pdf.setStrokeColor(HexColor(color));pdf.setLineWidth(1.4)
            lookup=totals[totals.scenario==scenario].set_index('year').value.to_dict()
            points=[(left+i*pw/max(len(years)-1,1),bottom+(lookup[year]-lo)/span*ph) if year in lookup else None for i,year in enumerate(years)]
            for a,b in zip(points,points[1:]):
                if a is not None and b is not None:pdf.line(*a,*b)
            pdf.setFillColor(HexColor(color));pdf.setFont('Helvetica',7);pdf.drawString(65,height-85-idx*11,scenario[:140])
        pdf.setFillColor(HexColor('#182D40'));pdf.setFont('Helvetica',8)
        for i,year in enumerate(years):pdf.drawCentredString(left+i*pw/max(len(years)-1,1),bottom-16,str(year))
        pdf.showPage()
        if metric["family"] in ("power", "energy"):
            active=[tech for tech in COLORS if tech in set(values.technology)]
            for scenario in scenarios:
                case=values[values.scenario==scenario];lookup=case.groupby(["year","technology"]).value.sum().to_dict()
                if any(v<0 for v in lookup.values()):continue
                pdf.setFillColor(HexColor("#182D40"));pdf.setFont("Helvetica-Bold",16);pdf.drawString(35,height-35,metric["title"])
                pdf.setFont("Helvetica",9);pdf.drawString(35,height-56,scenario[:135]+f" | annual values ({unit})")
                for i,tech in enumerate(active):
                    x=65+(i%6)*125;y=height-83-(i//6)*17
                    pdf.setFillColor(HexColor(COLORS[tech]));pdf.rect(x,y,8,8,stroke=0,fill=1)
                    pdf.setFillColor(HexColor("#182D40"));pdf.setFont("Helvetica",7);pdf.drawString(x+12,y,tech)
                left,bottom,pw,ph=65,65,width-105,height-200-(len(active)//6)*17
                ymax=max((sum(lookup.get((y,t),0) for t in active) for y in years),default=0)*1.1 or 1
                step=pw/len(years)
                for tick in range(6):
                    yy=bottom+ph*tick/5;pdf.setStrokeColor(HexColor('#D8DFE6'));pdf.line(left,yy,left+pw,yy)
                    pdf.setFillColor(HexColor('#182D40'));pdf.setFont('Helvetica',8);pdf.drawRightString(left-8,yy-3,f'{ymax*tick/5:.3g}')
                for i,year in enumerate(years):
                    current=0
                    for tech in active:
                        value=lookup.get((year,tech),0);pdf.setFillColor(HexColor(COLORS[tech]))
                        pdf.rect(left+(i+.15)*step,bottom+current/ymax*ph,step*.7,value/ymax*ph,stroke=0,fill=1);current+=value
                    pdf.setFillColor(HexColor('#182D40'));pdf.setFont('Helvetica',8);pdf.drawCentredString(left+(i+.5)*step,bottom-16,str(year))
                pdf.showPage()
    pdf.save()


def export_metrics(sources, spec, output, *, max_rows=1000000, timeout=600):
    from bokeh.embed import file_html
    from bokeh.resources import INLINE
    output = Path(output).resolve()
    if output.exists(): raise ValueError("Choose a new report output folder")
    validate_metrics_spec(spec)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="annual-report-") as temporary:
        staging = Path(temporary)/"report"
        staging.mkdir()
        results, coverage = collect_metrics(sources, spec, max_rows=max_rows, timeout=timeout, audit_output=staging)
        scenarios = [s.label for s in sources]
        (staging / "reports.html").write_text(file_html(metrics_document(results, coverage, spec, scenarios), INLINE, spec.get("title", "Annual solution reports")), encoding="utf-8")
        write_metrics_pdf(staging / "reports.pdf", results, spec, scenarios)
        imports = {s.label: json.loads((Path(s.path)/"import-provenance.json").read_text(encoding="utf-8"))
                   for s in sources if s.path and (Path(s.path)/"import-provenance.json").exists()}
        (staging / "audit.json").write_text(json.dumps({"specification":spec,"coverage":coverage,"imports":imports,"technology_colors":COLORS,
            "metric_files":{name:f"metric-{i+1:03d}.parquet" for i,(name,frame) in enumerate(results.items()) if not frame.empty}},indent=2),encoding="utf-8")
        staging.rename(output)
    return output
