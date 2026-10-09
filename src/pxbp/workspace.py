"""Versioned, declarative workspaces. Loading never executes Python or queries."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .comparison import MODES
from .pivot import AXES, SERIES
from .sources import Selection, load_sources

CHART_TYPES = ["Line", "Dot", "Dot-Line", "Bar", "Stacked Bar", "Stacked Area"]
PRESETS = {
    "Scenario stacks": {"x": "year", "series": "category_name", "facet": "scenario", "chart_type": "Stacked Bar", "net_total": True},
    "Scenario areas": {"x": "year", "series": "category_name", "facet": "scenario", "chart_type": "Stacked Area", "net_total": True},
    "Technology comparisons": {"x": "year", "series": "scenario", "facet": "category_name", "chart_type": "Dot-Line", "net_total": False},
}
PLOT_DEFAULTS = {"x": "start_date", "series": "scenario", "operation": "sum", "chart_type": "Line",
                 "facet": "None", "comparison": "Absolute", "baseline": "", "net_total": False,
                 "shared_axes": True, "columns": 3, "filters": {}, "colors": {}, "series_order": [], "scale": 1.0, "unit_label": ""}


def validate_plot(plot, labels):
    if not isinstance(plot, dict) or set(plot) - set(PLOT_DEFAULTS):
        raise ValueError("Unknown plot settings")
    value = {**PLOT_DEFAULTS, **plot}
    allowed = {"x": AXES, "series": SERIES, "operation": ["sum", "mean", "min", "max"],
               "chart_type": CHART_TYPES, "comparison": MODES, "facet": ["None", *SERIES]}
    for key, choices in allowed.items():
        if value[key] not in choices:
            raise ValueError(f"Unsupported plot {key}")
    if value["baseline"] and value["baseline"] not in labels:
        raise ValueError("Baseline must name a configured source")
    if value["comparison"] != "Absolute" and not value["baseline"]:
        raise ValueError("Comparison needs a baseline")
    if type(value["columns"]) is not int or not 1 <= value["columns"] <= 6:
        raise ValueError("Plot columns must be 1–6")
    for key in ("net_total", "shared_axes"):
        if type(value[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    if not isinstance(value["scale"], (int, float)) or not 0 < value["scale"] < float("inf"):
        raise ValueError("Plot scale must be positive and finite")
    if not isinstance(value["unit_label"], str) or len(value["unit_label"]) > 80:
        raise ValueError("Unit label must be a short string")
    if not isinstance(value["filters"], dict) or any(k not in SERIES for k in value["filters"]):
        raise ValueError("Filters must name a supported pivot dimension")
    if any(not isinstance(v, list) or any(not isinstance(s, str) for s in v) for v in value["filters"].values()):
        raise ValueError("Each filter must be an array of labels")
    if not isinstance(value["colors"], dict) or any(not isinstance(k, str) or not isinstance(v, str)
        or not re.fullmatch(r"#[0-9a-fA-F]{6}", v) for k, v in value["colors"].items()):
        raise ValueError("Colors must map labels to six-digit hex colors")
    if not isinstance(value["series_order"], list) or any(not isinstance(v, str) for v in value["series_order"]):
        raise ValueError("Series order must be an array of labels")
    return value


def read_workspace(path):
    path = Path(path).expanduser().resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    allowed = {"version", "sources", "query", "plot", "selected_sources", "report_preset"}
    if not isinstance(config, dict) or set(config) - allowed or config.get("version") != 1:
        raise ValueError("Workspace needs version 1 and sources, query, plot settings")
    sources = load_sources(path)
    if config.get("report_preset"):
        from .report_library import get_preset
        get_preset(config["report_preset"])
    selection = Selection(config.get("query", {}))
    labels = [s.label for s in sources]
    plot = validate_plot(config.get("plot", {}), labels)
    selected = config.get("selected_sources", labels)
    if not isinstance(selected, list) or not selected or any(not isinstance(s, str) for s in selected) or set(selected) - set(labels):
        raise ValueError("Selected sources must name configured solutions")
    if plot["comparison"] != "Absolute" and plot["baseline"] not in selected:
        raise ValueError("Selected sources must include the baseline")
    normalized = [{"label": s.label, **({"solution_id": s.solution_id} if s.solution_id else {"path": s.path})} for s in sources]
    return sources, {**config, "sources": normalized, "query": selection.query, "plot": plot, "selected_sources": selected}


def make_workspace(sources, query, plot, selected_sources=None):
    labels = [s.label for s in sources]
    query = dict(query)
    query.setdefault("aggregate_by", "none")
    Selection(query)
    return {"version": 1, "sources": [{"label": s.label, **({"solution_id": s.solution_id} if s.solution_id
        else {"path": s.path})} for s in sources], "query": query,
        "plot": validate_plot(plot, labels), "selected_sources": selected_sources or labels}
