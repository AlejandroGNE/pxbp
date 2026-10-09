"""Export a saved comparison workspace as an offline interactive chart snapshot."""
from __future__ import annotations

import html
import json
from pathlib import Path

import duckdb
import pandas as pd
from bokeh.embed import file_html
from bokeh.layouts import column
from bokeh.models import ColumnDataSource, DataTable, Div, TableColumn
from bokeh.resources import INLINE

from .cache import query_cached
from .comparison import compare
from .pivot import pivot
from .plotting import build_charts
from .sources import Selection
from .workspace import read_workspace


def export_snapshot(workspace_path, output, cache_dir=None, max_rows=1000000, timeout=600):
    sources, workspace = read_workspace(workspace_path)
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError("Snapshot output already exists; choose a new directory")
    sources = [s for s in sources if s.label in workspace["selected_sources"]]
    frames = [batch.frame for batch in query_cached(sources, Selection(workspace["query"], max_rows=max_rows, timeout=timeout), cache_dir)]
    if not frames:
        raise ValueError("No query results; no snapshot was published")
    frame = pd.concat(frames, ignore_index=True)
    plot = workspace["plot"]
    if workspace.get("report_preset"):
        from .report_library import prepare_annual, preset_plot
        frame = prepare_annual(frame, workspace["report_preset"])
        plot = preset_plot(workspace["report_preset"], plot["baseline"], [s.label for s in sources], plot)
    table = pivot(frame, x=plot["x"], series=plot["series"], operation=plot["operation"],
        filters={k: v for k, v in plot["filters"].items() if k != "scenario"}, facet=plot["facet"])
    table = compare(table, plot["baseline"], plot["comparison"], visible=plot["filters"].get("scenario"))
    charts, notes = build_charts(table, plot)
    preview = table.head(1000).copy()
    preview[plot["x"]] = preview[plot["x"]].astype(str)
    fields = list(dict.fromkeys([plot["x"], "scenario", plot["series"], "unit", "value", "absolute_value", "baseline_value", "comparison_status", "model_name"]))
    grid = DataTable(source=ColumnDataSource(preview[fields]), columns=[TableColumn(field=k, title=k) for k in fields], height=300, sizing_mode="stretch_width")
    layout = column(Div(text=f"<h1>Scenario comparison</h1><p>{html.escape(plot['comparison'])}; baseline: {html.escape(plot['baseline'])}. "
        f"{len(sources)} solutions; {len(frame):,} query rows; {len(table):,} pivot rows.</p>"
        "<p>Offline snapshot: pan, zoom, hover, and hide legend series. Reopen the workspace in PXBP to change queries or plot settings.</p>"),
        Div(text=html.escape(" ".join(notes))), charts, grid, sizing_mode="stretch_width")
    document = file_html(layout, INLINE, "Scenario comparison")
    output.mkdir(parents=True)
    try:
        (output / "comparison.html").write_text(document, encoding="utf-8")
        with duckdb.connect() as con:
            con.register("result", table)
            con.execute("COPY result TO ? (FORMAT PARQUET)", [str(output / "comparison.parquet")])
        (output / "workspace.private.json").write_text(json.dumps(workspace, indent=2), encoding="utf-8")
        models = frame.groupby("scenario").model_name.unique().map(list).to_dict()
        (output / "audit.json").write_text(json.dumps({"sources": workspace["sources"], "models": models,
            "query_rows": len(frame), "pivot_rows": len(table), "comparison_status": table.comparison_status.value_counts().to_dict(),
            "notes": notes, "workspace": workspace}, indent=2), encoding="utf-8")
        (output / "complete.json").write_text('{"complete": true}', encoding="utf-8")
    except Exception:
        (output / "INCOMPLETE.txt").write_text("Snapshot export failed; do not use partial files.", encoding="utf-8")
        raise
    return output
