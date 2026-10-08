"""Audited annual capacity additions and portable HTML/PDF reports."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import pandas as pd

from .sources import Selection, stream_query

# Technology identity is shared by every chart and export.
TECHNOLOGY_COLORS = {
    "Nuclear": "#820000", "Coal": "#000000", "Gas-CC": "#5E1688",
    "Gas-CT": "#C2A1DB", "Hydropower": "#187F94", "Geothermal": "#A96235",
    "Biopower": "#5B9844", "Onshore Wind": "#00B6EF", "Offshore Wind": "#106BA7",
    "UPV": "#FFC903", "DPV": "#FFAB02", "Battery": "#FF4A88",
    "Pumped Storage": "#CC0079",
}


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(spec, dict) or not {"queries", "assets"} <= spec.keys():
        raise ValueError("Report specification needs queries and assets")
    if not isinstance(spec["queries"], list) or not spec["queries"]:
        raise ValueError("Report queries must be a nonempty array")
    seen = set()
    for query in spec["queries"]:
        Selection(query)
        if query.get("period") != "Year" or query.get("properties") not in ("UnitsBuilt", "CapacityBuilt", "Units Built", "Capacity Built"):
            raise ValueError("Capacity additions require Year and UnitsBuilt or CapacityBuilt")
        if query.get("aggregate_by") or query.get("aggregate_type"):
            raise ValueError("Report queries must retain individual assets; remove aggregation")
        collection = query["collection"]
        if collection in seen:
            raise ValueError("Use one capacity query per collection")
        seen.add(collection)
    if not isinstance(spec["assets"], list):
        raise ValueError("assets must be an array")
    identities = set()
    for asset in spec["assets"]:
        identity = (asset["collection"], asset["object_name"])
        if identity in identities:
            raise ValueError(f"Duplicate asset mapping: {identity}")
        identities.add(identity)
        if asset.get("exclude_reason"):
            continue
        if not asset.get("region") or asset.get("technology") not in TECHNOLOGY_COLORS:
            raise ValueError(f"Asset needs region and a supported technology: {identity}")
        for value in [asset.get("capacity_mw"), *asset.get("capacity_mw_by_year", {}).values()]:
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
                raise ValueError(f"Per-unit power rating must be positive finite MW: {identity}")
    if spec.get("years") is not None and (not spec["years"] or any(type(y) is not int for y in spec["years"])):
        raise ValueError("years must be a nonempty array of integer years")
    return spec


def capacity_rows(frame, spec):
    """Do not silently sum bands, samples, models, or unmapped assets."""
    assets = {(a["collection"].removeprefix("System"), a["object_name"]): a for a in spec["assets"]}
    rows, excluded = [], []
    seen = set()
    dimensions = {}
    years = set(spec.get("years", []))
    for row in frame.to_dict("records"):
        year = pd.Timestamp(row["start_date"]).year
        if years and year not in years:
            continue
        value = float(row["value"])
        if not math.isfinite(value) or value < -1e-8:
            raise ValueError("Units Built/Capacity Built must contain finite nonnegative additions")
        identity = (row["collection_name"].removeprefix("System"), row["object_name"])
        unique = (row["scenario"], *identity, year)
        if unique in seen:
            raise ValueError(f"Multiple rows for one asset/year; select one band/sample/model: {unique}")
        seen.add(unique)
        dim = tuple(str(row.get(k, "")) for k in ("phase_name", "period_type_name", "timeslice_name", "sample_name", "model_name", "band_id"))
        scenario_collection = (row["scenario"], row["collection_name"])
        if scenario_collection in dimensions and dimensions[scenario_collection] != dim:
            raise ValueError("Mixed phase/period/timeslice/sample/model/band; narrow report queries")
        dimensions[scenario_collection] = dim
        if row.get("period_type_name") != "Year":
            raise ValueError("Report results must be annual")
        if row["property_name"] not in ("Units Built", "UnitsBuilt", "Capacity Built", "CapacityBuilt"):
            raise ValueError("Unexpected property in capacity additions")
        if abs(value) <= 1e-8:
            continue
        asset = assets.get(identity)
        if asset is None:
            raise ValueError(f"Positive build has no asset mapping: {identity}")
        if asset.get("exclude_reason"):
            excluded.append({"scenario": row["scenario"], "collection": identity[0], "object_name": identity[1],
                             "year": year, "value": value, "unit": row["unit"], "reason": asset["exclude_reason"]})
            continue
        if row["property_name"] in ("Units Built", "UnitsBuilt"):
            if row["unit"] not in ("-", "", "units", "Units"):
                raise ValueError("Units Built must be dimensionless")
            rating = asset.get("capacity_mw_by_year", {}).get(str(year), asset.get("capacity_mw"))
            if rating is None:
                raise ValueError(f"Units Built requires an audited per-unit MW rating: {identity}, {year}")
            mw = value * rating
            method = "Units Built x per-unit MW"
        else:
            factors = {"MW": 1, "GW": 1000, "kW": .001}
            if row["unit"] not in factors:
                raise ValueError("Capacity Built must use MW, GW or kW; energy units are unsupported")
            mw = value * factors[row["unit"]]
            rating = None
            method = "Reported Capacity Built"
        rows.append({"scenario": row["scenario"], "collection": identity[0], "object_name": identity[1],
                     "year": year, "region": asset["region"], "technology": asset["technology"],
                     "capacity_mw": mw, "reported_value": value, "reported_unit": row["unit"],
                     "per_unit_mw": rating, "method": method})
    columns = ["scenario", "collection", "object_name", "year", "region", "technology", "capacity_mw",
               "reported_value", "reported_unit", "per_unit_mw", "method"]
    return pd.DataFrame(rows, columns=columns), excluded


def collect_capacity(sources, spec, *, max_rows=1000000, timeout=600):
    frames = []
    remaining = max_rows
    for query in spec["queries"]:
        selection = Selection(query, max_rows=remaining, timeout=timeout)
        query_scenarios = set()
        for batch in stream_query(sources, selection):
            query_scenarios.add(batch.source.label)
            frames.append(batch.frame)
            remaining -= len(batch.frame)
        missing = {s.label for s in sources} - query_scenarios
        if missing:
            raise ValueError("No rows for collection " + query["collection"] + ": " + ", ".join(sorted(missing)))
        if remaining <= 0:
            raise ValueError("Report row limit reached; increase max_rows or narrow queries")
    if not frames:
        raise ValueError("Report queries returned no data")
    frame = pd.concat(frames, ignore_index=True)
    missing = {s.label for s in sources} - set(frame.scenario)
    if missing:
        raise ValueError("No reported builds for scenarios: " + ", ".join(sorted(missing)))
    rows, excluded = capacity_rows(frame, spec)
    return rows, excluded, sorted(set(spec.get("years") or pd.to_datetime(frame.start_date).dt.year.tolist()))


def chart_data(rows, scenarios, regions, years=None):
    if years is not None:
        rows = rows[rows.year.isin(years)]
    totals = rows.groupby(["scenario", "region", "technology"]).capacity_mw.sum().to_dict()
    factors = [(s, r) for s in scenarios for r in regions]
    result = {"x": factors}
    for tech in TECHNOLOGY_COLORS:
        result[tech] = [totals.get((s, r, tech), 0) / 1000 for s, r in factors]
    result["total"] = [sum(result[t][i] for t in TECHNOLOGY_COLORS) for i in range(len(factors))]
    return result


def report_document(rows, excluded, years, spec, scenarios):
    from bokeh.layouts import column
    from bokeh.models import (ColumnDataSource, CustomJS, DataTable, Div, FactorRange,
                              HoverTool, Select, TabPanel, TableColumn, Tabs)
    from bokeh.plotting import figure

    regions = sorted({a["region"] for a in spec["assets"] if not a.get("exclude_reason")})
    data = chart_data(rows, [scenarios[0]], regions)
    source = ColumnDataSource(data)
    views = {}
    for name, cases in [("All scenarios", scenarios), *[(s, [s]) for s in scenarios]]:
        views[name] = {str(y): chart_data(rows, cases, regions, [y]) for y in years}
        views[name]["All years"] = chart_data(rows, cases, regions)
    title = spec.get("title", "New capacity by region")
    chart = figure(x_range=FactorRange(*data["x"]), height=580, sizing_mode="stretch_width",
                   title=title, tools="pan,wheel_zoom,box_zoom,reset,save")
    chart.vbar_stack(list(TECHNOLOGY_COLORS), x="x", width=.78, source=source,
                     color=list(TECHNOLOGY_COLORS.values()), legend_label=list(TECHNOLOGY_COLORS))
    chart.add_tools(HoverTool(tooltips=[("Scenario / region", "@x"), ("Technology", "$name"),
                                        ("New capacity (GW)", "@$name{0.000}"), ("Total (GW)", "@total{0.000}")]))
    chart.yaxis.axis_label = "New capacity (GW)"
    chart.y_range.start = 0
    chart.xaxis.major_label_orientation = .9
    chart.legend.location = "top_left"
    chart.legend.click_policy = "hide"
    chart.add_layout(chart.legend[0], "right")
    select = Select(title="Build year", value="All years", options=["All years", *map(str, years)])
    case_select = Select(title="Scenario", value=scenarios[0], options=["All scenarios", *scenarios])
    callback = CustomJS(args={"source": source, "views": views, "plot": chart,
                             "year_select": select, "case_select": case_select, "base_title": title}, code="""
        source.data = views[case_select.value][year_select.value];
        plot.x_range.factors = source.data.x;
        source.change.emit();
        plot.title.text = base_title + ' - ' + case_select.value + ' - ' + year_select.value;
    """)
    select.js_on_change("value", callback)
    case_select.js_on_change("value", callback)
    summary = (rows.groupby(["scenario", "region", "year", "technology"], as_index=False).capacity_mw.sum())
    summary["capacity_gw"] = summary.capacity_mw / 1000
    table = DataTable(source=ColumnDataSource(summary), columns=[TableColumn(field=k, title=k.replace("_", " ").title())
                      for k in ["scenario", "region", "year", "technology", "capacity_gw"]],
                      sizing_mode="stretch_width", height=600, index_position=None)
    escaped = html.escape(spec.get("notes", ""))
    methods = Div(text=f"<h2>Calculation and coverage</h2><p>Annual additions are summed once over the selected years. "
                  f"Units Built is multiplied by the explicit per-unit MW rating. Reported Capacity Built is converted to MW. "
                  f"The report includes generation and battery power capacity according to the asset mapping.</p>"
                  f"<p>Reporting years: {', '.join(map(str, years))}. Positive build rows included: {len(rows)}. "
                  f"Rows excluded with explicit reasons: {len(excluded)}.</p><p>{escaped}</p>"
                  f"<p>Asset details, exclusions, queries and technology colors are recorded in the accompanying audit.json.</p>",
                  sizing_mode="stretch_width")
    return column(Div(text=f"<h1>{html.escape(title)}</h1><p>Choose a year, hover to inspect values, and click legend items to hide technologies.</p>"),
                  Tabs(tabs=[TabPanel(title="New capacity", child=column(case_select, select, chart)),
                             TabPanel(title="Annual totals", child=table), TabPanel(title="Methods", child=methods)]),
                  sizing_mode="stretch_width")


def write_pdf(path, rows, excluded, years, spec, scenarios):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import simpleSplit

    width, height = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=(width, height))
    c.setTitle(spec.get("title", "New capacity by region"))
    regions = sorted({a["region"] for a in spec["assets"] if not a.get("exclude_reason")})
    techs = list(TECHNOLOGY_COLORS)
    active = [t for t in techs if t in set(rows.technology)]
    page_number = 0

    def heading(text, subtitle):
        nonlocal page_number
        page_number += 1
        c.setFillColor(HexColor("#182D40")); c.setFont("Helvetica-Bold", 17)
        c.drawString(40, height - 40, text[:100])
        if spec.get("status"):
            c.setFont("Helvetica-Bold", 11); c.drawRightString(width - 35, height - 40, str(spec["status"]).upper())
        c.setFont("Helvetica", 10); c.drawString(40, height - 59, subtitle[:140])
        c.setFont("Helvetica", 8); c.drawRightString(width - 35, 20, str(page_number))

    # Separate pages keep axis labels readable even for many model regions.
    for scenario in scenarios:
        for offset in range(0, len(regions), 10):
            subset = regions[offset:offset + 10]
            heading(spec.get("title", "New capacity by region"), f"{scenario} | {years[0]}-{years[-1]} | annual additions summed once")
            data = chart_data(rows, [scenario], subset)
            ymax = max(data["total"], default=0) * 1.1 or 1
            left, bottom, plot_width, plot_height = 70, 135, width - 285, height - 240
            c.setLineWidth(.3)
            for tick in range(6):
                y = bottom + plot_height * tick / 5
                c.setStrokeColor(HexColor("#D8DFE6")); c.line(left, y, left + plot_width, y)
                c.setFillColor(HexColor("#182D40")); c.setFont("Helvetica", 9)
                c.drawRightString(left - 8, y - 3, f"{ymax * tick / 5:.2f}")
            c.saveState(); c.translate(24, bottom + plot_height / 2); c.rotate(90)
            c.drawCentredString(0, 0, "New capacity (GW)"); c.restoreState()
            step = plot_width / max(len(subset), 1)
            for i, region in enumerate(subset):
                current = 0
                for tech in active:
                    value = data[tech][i]
                    c.setFillColor(HexColor(TECHNOLOGY_COLORS[tech]))
                    c.rect(left + step * (i + .17), bottom + current / ymax * plot_height,
                           step * .66, value / ymax * plot_height, stroke=0, fill=1)
                    current += value
                c.setFillColor(HexColor("#182D40")); c.setFont("Helvetica", 8)
                c.drawCentredString(left + step * (i + .5), bottom + current / ymax * plot_height + 5, f"{current:.2f}")
                c.saveState(); c.translate(left + step * (i + .5), bottom - 10); c.rotate(55)
                c.drawRightString(0, 0, region[:42]); c.restoreState()
            for i, tech in enumerate(active):
                y = height - 120 - i * 22
                c.setFillColor(HexColor(TECHNOLOGY_COLORS[tech])); c.rect(width - 190, y - 2, 12, 12, stroke=0, fill=1)
                c.setFillColor(HexColor("#182D40")); c.setFont("Helvetica", 10); c.drawString(width - 171, y, tech)
            c.showPage()
    # Annual build timing uses a single system total for each scenario, with region detail in HTML.
    for scenario in scenarios:
        heading("New capacity by year", f"{scenario} | system total | GW")
        annual = rows[rows.scenario == scenario].groupby(["year", "technology"]).capacity_mw.sum().to_dict()
        ymax = max((sum(annual.get((y, t), 0) for t in active) / 1000 for y in years), default=0) * 1.1 or 1
        left, bottom, pw, ph = 65, 65, width - 100, height - 180
        for tick in range(6):
            y = bottom + ph * tick / 5
            c.setStrokeColor(HexColor("#D8DFE6")); c.line(left, y, left + pw, y)
            c.setFillColor(HexColor("#182D40")); c.setFont("Helvetica", 9); c.drawRightString(left - 8, y - 3, f"{ymax*tick/5:.2f}")
        step = pw / len(years)
        for i, year in enumerate(years):
            current = 0
            for tech in active:
                v = annual.get((year, tech), 0) / 1000
                c.setFillColor(HexColor(TECHNOLOGY_COLORS[tech]))
                c.rect(left + (i + .15) * step, bottom + current / ymax * ph, step * .7, v / ymax * ph, stroke=0, fill=1)
                current += v
            c.setFillColor(HexColor("#182D40")); c.setFont("Helvetica", 8); c.drawCentredString(left + (i + .5)*step, bottom - 16, str(year))
        for i, tech in enumerate(active):
            x = 65 + (i % 6) * 124; y = height - 85 - (i // 6)*17
            c.setFillColor(HexColor(TECHNOLOGY_COLORS[tech])); c.rect(x, y, 8, 8, stroke=0, fill=1)
            c.setFillColor(HexColor("#182D40")); c.setFont("Helvetica", 8); c.drawString(x + 12, y, tech)
        c.showPage()
    heading("Calculation and coverage", "Definitions and exclusions")
    lines = ["This report measures new power capacity, not installed capacity or storage energy.",
             "Units Built x audited per-unit MW rating; reported Capacity Built converted to MW.",
             "Annual additions are counted once; no multi-year multiplier is applied.",
             f"Years: {', '.join(map(str, years))}", f"Included positive asset/year rows: {len(rows)}; excluded rows: {len(excluded)}.",
             spec.get("notes", ""), "See audit.json for asset-level values, explicit exclusions, query selections and technology colors."]
    c.setFont("Helvetica", 11); c.setFillColor(HexColor("#182D40")); y = height - 100
    for paragraph in lines:
        for line in simpleSplit(paragraph, "Helvetica", 11, width - 90):
            c.drawString(45, y, line); y -= 16
        y -= 10
    c.save()


def export_capacity(sources, spec, output, *, max_rows=1000000, timeout=600):
    from bokeh.embed import file_html
    from bokeh.resources import INLINE
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new report output folder; existing reports are never overwritten")
    rows, excluded, years = collect_capacity(sources, spec, max_rows=max_rows, timeout=timeout)
    output.mkdir(parents=True)
    scenarios = [s.label for s in sources]
    (output / "capacity.html").write_text(file_html(report_document(rows, excluded, years, spec, scenarios), INLINE,
                                                  spec.get("title", "New capacity by region")), encoding="utf-8")
    write_pdf(output / "capacity.pdf", rows, excluded, years, spec, scenarios)
    imports = {}
    for source in sources:
        if source.path and (Path(source.path) / "import-provenance.json").is_file():
            imports[source.label] = json.loads((Path(source.path) / "import-provenance.json").read_text(encoding="utf-8"))
    (output / "audit.json").write_text(json.dumps({"specification": spec, "years": years,
        "sources": [{"label": s.label, "solution_id": s.solution_id, "path": s.path} for s in sources],
        "imports": imports, "technology_colors": TECHNOLOGY_COLORS, "included": rows.to_dict("records"), "excluded": excluded}, indent=2), encoding="utf-8")
    return output
