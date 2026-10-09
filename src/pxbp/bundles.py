"""Declarative annual report bundles sharing sources, baseline, filters, and colors."""
from __future__ import annotations

from copy import deepcopy
import html
import json
from pathlib import Path
import threading

import duckdb
import pandas as pd
from bokeh.embed import file_html
from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, CustomJS, DataTable, Div, Select, TableColumn
from bokeh.resources import INLINE

from .cache import query_cached
from .comparison import compare, MODES
from .pivot import pivot
from .plotting import build_charts
from .report_library import DEFAULT_SECTIONS, get_preset, prepare_annual, preset_plot, preset_query
from .sources import Source, Selection, Cancelled


def validate_bundle(config, base_dir=None):
    allowed = {"kind", "version", "title", "sources", "selected_sources", "baseline", "query_filters", "colors", "series_order", "sections"}
    if not isinstance(config, dict) or set(config) - allowed or config.get("kind") != "annual-report-bundle" or config.get("version") != 1:
        raise ValueError("Expected a version 1 annual-report-bundle")
    config = deepcopy(config)
    items = config.get("sources")
    if not isinstance(items, list) or not items:
        raise ValueError("Report bundle needs sources")
    sources = []
    for item in items:
        if not isinstance(item, dict) or set(item) not in ({"label", "path"}, {"label", "solution_id"}):
            raise ValueError("Sources need label and path or solution_id")
        if "path" in item:
            path = Path(item["path"]).expanduser()
            item["path"] = str(((Path(base_dir) if base_dir else Path.cwd()) / path).resolve())
        sources.append(Source(**item))
    labels = [s.label for s in sources]
    if len(set(labels)) != len(labels):
        raise ValueError("Source labels must be unique")
    if config.get("baseline") not in labels:
        raise ValueError("Bundle baseline must name a configured source")
    selected = config.get("selected_sources", labels)
    if not isinstance(selected, list) or not selected or any(not isinstance(v, str) for v in selected) or set(selected) - set(labels):
        raise ValueError("Bundle selected_sources must name configured sources")
    if config["baseline"] not in selected:
        raise ValueError("Bundle selected_sources must include the baseline")
    config["selected_sources"] = selected
    config.setdefault("title", "Annual scenario comparison")
    if not isinstance(config["title"], str) or not config["title"].strip():
        raise ValueError("Bundle title must be nonempty text")
    if not isinstance(config.get("query_filters", {}), dict):
        raise ValueError("Bundle query_filters must be an object")
    sections = config.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 50:
        raise ValueError("Use 1–50 report sections")
    ids = set()
    for section in sections:
        if not isinstance(section, dict) or set(section) - {"id", "title", "preset", "views", "plot", "query_filters"}:
            raise ValueError("Unknown report section fields")
        identifier = section.get("id")
        if not isinstance(identifier, str) or not identifier or not all(c.isalnum() or c in "-_" for c in identifier) or identifier in ids:
            raise ValueError("Section IDs must be unique letters, digits, hyphens, or underscores")
        ids.add(identifier)
        if not isinstance(section.get("query_filters", {}), dict) or not isinstance(section.get("plot", {}), dict):
            raise ValueError("Section query_filters and plot must be objects")
        definition = get_preset(section.get("preset"))
        section.setdefault("title", definition["title"])
        if not isinstance(section["title"], str):
            raise ValueError("Section title must be text")
        views = section.get("views", ["Absolute", "Difference"])
        if not isinstance(views, list) or not 1 <= len(views) <= 4 or any(v not in MODES for v in views) or len(set(views)) != len(views):
            raise ValueError("Section views must select unique comparison modes")
        section["views"] = views
        preset_query(section["preset"], {**config.get("query_filters", {}), **section.get("query_filters", {})})
        overrides = {"colors": config.get("colors", {}), "series_order": config.get("series_order", []), **section.get("plot", {})}
        # The shared baseline cannot be overridden by an individual section.
        if "baseline" in overrides or "comparison" in overrides:
            raise ValueError("Section plot cannot override the shared baseline or views")
        plot = preset_plot(section["preset"], config["baseline"], labels, overrides)
        if plot["chart_type"] in {"Stacked Bar", "Stacked Area"} and any(v in {"Ratio", "Percent change"} for v in views):
            raise ValueError("Percentage and ratio sections need an unstacked chart")
    return sources, config


def read_bundle(path):
    path = Path(path).expanduser().resolve()
    return validate_bundle(json.loads(path.read_text(encoding="utf-8-sig")), path.parent)


def make_bundle(sources, baseline, *, presets=None, selected_sources=None, query_filters=None, colors=None, series_order=None):
    config = {"kind": "annual-report-bundle", "version": 1, "title": "Annual scenario comparison", "baseline": baseline,
        "sources": [{"label": s.label, **({"solution_id": s.solution_id} if s.solution_id else {"path": s.path})} for s in sources],
        "selected_sources": selected_sources or [s.label for s in sources], "query_filters": query_filters or {},
        "colors": colors or {}, "series_order": series_order or [],
        "sections": [{"id": identifier, "preset": identifier, "views": ["Absolute", "Difference"]} for identifier in (presets or DEFAULT_SECTIONS)]}
    return validate_bundle(config)[1]


def build_bundle(config, cache_dir=None, *, max_rows=1000000, timeout=600, cancel=None, progress=None, refresh=False):
    sources, config = validate_bundle(config)
    sources = [s for s in sources if s.label in config["selected_sources"]]
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    remaining = max_rows
    results = []
    for index, section in enumerate(config["sections"]):
        if cancel.is_set():
            raise Cancelled("Report bundle cancelled")
        query = preset_query(section["preset"], {**config.get("query_filters", {}), **section.get("query_filters", {})})
        definition = get_preset(section["preset"])
        plot = preset_plot(section["preset"], config["baseline"], [s.label for s in sources],
            {"colors": config.get("colors", {}), "series_order": config.get("series_order", []), **section.get("plot", {})})
        result = {"section": section, "definition": definition, "query": query, "plot": plot, "coverage": [], "views": {}, "raw": pd.DataFrame(), "normalized": pd.DataFrame()}
        progress(f"Section {index+1}/{len(config['sections'])}: {section['title']}")
        frames = []
        for source in sources:
            if remaining < 1:
                raise ValueError("Report bundle row budget exhausted; select fewer sections/sources or narrow annual dates")
            selection = Selection(query, max_rows=remaining, timeout=timeout)
            chunks = []
            try:
                for batch in query_cached([source], selection, cache_dir, cancel,
                    lambda s, origin: progress(f"{section['title']} — {s.label}: {'cached' if origin == 'cache' else 'querying'}"), refresh=refresh):
                    remaining -= len(batch.frame)
                    chunks.append(batch.frame)
            except (Cancelled, TimeoutError):
                raise
            except Exception as exc:
                # A budget overflow is fatal, not an unavailable property.
                if "Row limit" in str(exc) or "budget" in str(exc):
                    raise
                result["coverage"].append({"scenario": source.label, "status": "error", "reason": str(exc)})
                continue
            raw = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            if raw.empty:
                result["coverage"].append({"scenario": source.label, "status": "unavailable", "rows": 0, "reason": "No reported measurements match this annual query"})
                continue
            try:
                normalized = prepare_annual(raw, section["preset"])
            except ValueError as exc:
                result["coverage"].append({"scenario": source.label, "status": "incompatible", "rows": len(raw), "reason": str(exc)})
                continue
            frames.append((raw, normalized))
            result["coverage"].append({"scenario": source.label, "status": "available", "rows": len(raw),
                "models": sorted(set(raw.model_name)), "reported_units": sorted(set(raw.unit)),
                "reported_properties": sorted(set(raw.property_name))})
        if frames:
            result["raw"] = pd.concat([pair[0] for pair in frames], ignore_index=True)
            result["normalized"] = pd.concat([pair[1] for pair in frames], ignore_index=True)
            # Validate again across sources (e.g., native emission mass units).
            try:
                normalized = prepare_annual(result["raw"], section["preset"])
                result["normalized"] = normalized
                table = pivot(normalized, x=plot["x"], series=plot["series"], operation=plot["operation"],
                    facet=plot["facet"], filters={k:v for k,v in plot["filters"].items() if k != "scenario"})
                for mode in section["views"]:
                    try:
                        compared = compare(table, config["baseline"], mode, visible=plot["filters"].get("scenario"))
                        result["views"][mode] = {"table": compared, "plot": {**plot, "comparison": mode}, "status": "available"}
                    except ValueError as exc:
                        result["views"][mode] = {"status": "unavailable", "reason": str(exc)}
            except ValueError as exc:
                result["reason"] = str(exc)
        result["status"] = "complete" if result["views"] and all(v["status"] == "available" for v in result["views"].values()) and all(c["status"] == "available" for c in result["coverage"]) else "partial" if result["views"] else "unavailable"
        results.append(result)
    return {"config": config, "sections": results, "query_rows": max_rows - remaining}


def section_layout(result, *, scenarios=None):
    columns = []
    for mode, view in result["views"].items():
        if view["status"] != "available":
            columns.append(column(Div(text=f"<h3>{html.escape(mode)}</h3><p>Unavailable: {html.escape(view['reason'])}</p>"), sizing_mode="stretch_width"))
            continue
        table = view["table"]
        if scenarios:
            table = table[table.scenario.isin(scenarios)]
        if table.empty:
            columns.append(column(Div(text=f"<h3>{html.escape(mode)}</h3><p>No measurements match the display filters.</p>"), sizing_mode="stretch_width"))
            continue
        chart, notes = build_charts(table, view["plot"])
        invalid = int((~table.comparison_status.isin(["matched", "absolute"])).sum())
        columns.append(column(Div(text=f"<h3>{html.escape(mode)}</h3><p>{invalid:,} missing or undefined comparisons. {html.escape(' '.join(notes))}</p>"), chart, sizing_mode="stretch_width"))
    missing = [f"{c['scenario']}: {c['status']} ({c.get('reason', '')})" for c in result["coverage"] if c["status"] != "available"]
    heading = Div(text=f"<h2>{html.escape(result['section']['title'])}</h2><p>{html.escape(result['definition']['note'])}</p>"
        f"<p>Coverage: {html.escape(result['status'])}. {html.escape('; '.join(missing))}</p>" +
        (f"<p>{html.escape(result['reason'])}</p>" if result.get("reason") else ""))
    return column(heading, row(*columns, sizing_mode="stretch_width") if columns else Div(text="No usable measurements were reported for this section."), sizing_mode="stretch_width")


def offline_layout(bundle):
    config = bundle["config"]
    sections = [section_layout(result) for result in bundle["sections"]]
    selector = Select(title="Report section", options=[(str(i), r["section"]["title"]) for i,r in enumerate(bundle["sections"])], value="0", width=400)
    for index, section in enumerate(sections):
        section.visible = index == 0
    selector.js_on_change("value", CustomJS(args={"sections": sections}, code="sections.forEach((section, index) => section.visible = index === Number(cb_obj.value));"))
    summary = "; ".join(f"{r['section']['title']}: {r['status']}" for r in bundle["sections"])
    return column(Div(text=f"<h1>{html.escape(config['title'])}</h1><p>Shared baseline: {html.escape(config['baseline'])}; "
        f"{len(config['selected_sources'])} solutions; {bundle['query_rows']:,} queried rows.</p>"
        "<p>Offline report: choose a section, pan, zoom, hover, and hide legend series. Change queries or baseline in the live application.</p>"
        f"<details><summary>All section coverage</summary><p>{html.escape(summary)}</p></details>"), selector, *sections, sizing_mode="stretch_width")


def offline_document(bundle):
    """Keep all data offline, but create chart models only for the selected section."""
    from bokeh.embed import json_item
    config = bundle["config"]
    items = [json_item(section_layout(result), "chart-root") for result in bundle["sections"]]
    # Escaping '<' prevents embedded data from ending the enclosing script tag.
    script_json = lambda value: json.dumps(value).replace("<", "\\u003c")
    options = "".join(f'<option value="{index}">{html.escape(r["section"]["title"])}</option>' for index,r in enumerate(bundle["sections"]))
    summary = "; ".join(f"{r['section']['title']}: {r['status']}" for r in bundle["sections"])
    return f'''<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(config["title"])}</title>
<style>body{{font:14px Arial,sans-serif;margin:20px;color:#111827}}select{{padding:8px;min-width:300px;margin:10px 0}}iframe{{width:100%;height:1000px;border:0}}details{{margin:12px 0}}</style></head><body>
<h1>{html.escape(config["title"])}</h1>
<p>Shared baseline: {html.escape(config["baseline"])}; {len(config["selected_sources"])} solutions; {bundle["query_rows"]:,} queried rows.</p>
<p>Offline report: choose a section, pan, zoom, hover, and hide legend series. Change queries or baseline in the live application.</p>
<details><summary>All section coverage</summary><p>{html.escape(summary)}</p></details>
<label for="report-section">Report section</label><br><select id="report-section">{options}</select>
<iframe id="report-view" title="Selected report charts"></iframe>
<noscript>Enable JavaScript to view the interactive report charts.</noscript>
<script type="application/json" id="report-data">{script_json(items)}</script>
<script>
const reports=JSON.parse(document.getElementById("report-data").textContent);
const resources={script_json(INLINE.render())};
const frame=document.getElementById("report-view");
frame.addEventListener("load",()=>{{
    const root=frame.contentDocument.getElementById("chart-root");
    if (!root) return;
    const resize=()=>frame.style.height=Math.max(1000,root.getBoundingClientRect().height+40)+"px";
    new frame.contentWindow.ResizeObserver(resize).observe(root);
    resize();
}});
function display(index){{
    // Replacing the frame also releases the previous section's document and views.
    frame.style.height="1000px";
    const item=JSON.stringify(reports[index]).replaceAll("<","\\\\u003c");
    frame.srcdoc='<!doctype html><html><head><meta charset="utf-8">'+resources+'</head><body style="margin:0"><div id="chart-root"></div><script>Bokeh.embed.embed_item('+item+',"chart-root");<\\/script></body></html>';
}}
document.getElementById("report-section").addEventListener("change",event=>display(Number(event.target.value)));
display(0);
</script></body></html>'''


def export_bundle(spec_path, output, cache_dir=None, *, max_rows=1000000, timeout=600, progress=None):
    _, config = read_bundle(spec_path)
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError("Bundle output already exists; choose a new folder")
    bundle = build_bundle(config, cache_dir, max_rows=max_rows, timeout=timeout, progress=progress)
    document = offline_document(bundle)
    output.mkdir(parents=True)
    try:
        (output / "reports.html").write_text(document, encoding="utf-8")
        (output / "bundle.private.json").write_text(json.dumps(bundle["config"], indent=2), encoding="utf-8")
        audit = {"configuration": bundle["config"], "query_rows": bundle["query_rows"], "sections": []}
        with duckdb.connect() as con:
            for result in bundle["sections"]:
                identifier = result["section"]["id"]
                record = {"id": identifier, "title": result["section"]["title"], "preset": result["section"]["preset"], "status": result["status"], "query": result["query"], "coverage": result["coverage"], "views": {}}
                if not result["raw"].empty:
                    con.register("raw", result["raw"])
                    con.execute("COPY raw TO ? (FORMAT PARQUET)", [str(output / (identifier + "-raw.parquet"))])
                for mode, view in result["views"].items():
                    detail = {"status": view["status"]}
                    if view["status"] == "available":
                        con.register("view", view["table"])
                        con.execute("COPY view TO ? (FORMAT PARQUET)", [str(output / (identifier + "-" + mode.lower().replace(" ", "-") + ".parquet"))])
                        detail.update(rows=len(view["table"]), comparison_status=view["table"].comparison_status.value_counts().to_dict(), plot=view["plot"])
                    else:
                        detail["reason"] = view["reason"]
                    record["views"][mode] = detail
                audit["sections"].append(record)
        from .bundle_pdf import export_bundle_pdf
        export_bundle_pdf(bundle, output / "reports.pdf")
        (output / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        (output / "complete.json").write_text(json.dumps({"processing_complete": True,
            "all_sections_available": all(r["status"] == "complete" for r in bundle["sections"])}), encoding="utf-8")
    except Exception:
        (output / "INCOMPLETE.txt").write_text("Bundle export failed; do not use partial files.", encoding="utf-8")
        raise
    return output
