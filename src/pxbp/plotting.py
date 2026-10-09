"""Shared renderer for live pivots and offline comparison snapshots."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from bokeh.layouts import gridplot
from bokeh.models import ColumnDataSource, HoverTool, Range1d, Legend
from bokeh.plotting import figure

from .reports import TECHNOLOGY_COLORS

# These same technology identities are used by audited annual reports.
COLORS = {**TECHNOLOGY_COLORS, "upv": "#FFC903", "wind-ons": "#00B6EF", "wind-ofs": "#106BA7",
          "gas-cc": "#5E1688", "gas-ct": "#C2A1DB", "battery": "#FF4A88", "coal": "#000000",
          "nuclear": "#820000", "hydro": "#187F94", "geothermal": "#A96235", "biopower": "#5B9844"}


def color_for(label, overrides):
    if label in overrides:
        return overrides[label]
    if label in COLORS:
        return COLORS[label]
    # Stable across filtering, ordering, restarts, and panels; no color cycling.
    return "#" + hashlib.sha256(str(label).encode()).hexdigest()[:6]


def build_charts(table, plot, *, panel_limit=120, series_limit=100):
    x, series = plot["x"], plot["series"]
    scale = plot["scale"] if plot["comparison"] in {"Absolute", "Difference"} else 1.0
    stacked = plot["chart_type"] in {"Stacked Bar", "Stacked Area"}
    if stacked and plot["comparison"] in {"Percent change", "Ratio"}:
        raise ValueError("Component percentages and ratios cannot be stacked. Choose Line, Dot-Line, or Bar.")
    # A property/unit/reported-series choice gets its own panel, never a mixed stack.
    panel_keys = [c for c in ("collection_name", "class_name", "property_name", "unit", "phase_name",
                              "period_type_name", "timeslice_name", "sample_name", "band_id")
                  if c in table and c != x]
    if plot["comparison"] == "Absolute" and "model_name" in table and table.groupby("scenario").model_name.nunique().gt(1).any():
        panel_keys.append("model_name")
    if plot["facet"] != "None" and plot["facet"] not in panel_keys and plot["facet"] != x:
        panel_keys.append(plot["facet"])
    # Stacking different scenarios is misleading: automatically facet scenarios.
    if stacked and series != "scenario" and "scenario" not in panel_keys and x != "scenario":
        panel_keys.append("scenario")
    panels = list(table.groupby(panel_keys, dropna=False, observed=True, sort=False)) if panel_keys else [((), table)]
    charts, notes, bounds = [], [], []
    if len(panels) > panel_limit:
        notes.append(f"Showing {panel_limit} of {len(panels)} panels; narrow filters to see the rest.")
    for identity, panel in panels[:panel_limit]:
        identity = identity if isinstance(identity, tuple) else (identity,)
        title = " | ".join((plot.get("unit_label") or str(v)) if k == "unit" and plot["comparison"] not in {"Ratio", "Percent change"} else str(v) for k, v in zip(panel_keys, identity)
                           if str(v) and (k in {"property_name", "unit", plot["facet"], "scenario"} or table[k].nunique(dropna=False) > 1))
        # Facet titles expose source model names without making them comparison keys.
        models = sorted(set(panel.model_name)) if "model_name" in panel else []
        if len(models) == 1 and models[0] and models[0] not in title:
            title += f" | model: {models[0]}"
        categorical = x != "start_date"
        xs = sorted(panel[x].drop_duplicates().tolist())
        if not xs:
            continue
        labels = [str(v) for v in xs]
        kwargs = {"x_range": labels} if categorical else {"x_axis_type": "datetime"}
        if not categorical and len(xs) == 1:
            stamp = pd.Timestamp(xs[0]).value / 1e6
            kwargs["x_range"] = (stamp - 86400000, stamp + 86400000)
        chart = figure(title=title or "Values", height=350, width=450,
                       tools="pan,wheel_zoom,box_zoom,reset,save", **kwargs)
        chart.xaxis.axis_label = x
        suffix = "%" if plot["comparison"] == "Percent change" else "ratio" if plot["comparison"] == "Ratio" else (plot.get("unit_label") or str(panel.unit.iloc[0]))
        chart.yaxis.axis_label = f"{plot['comparison']} ({suffix})" + (f" × {plot['scale']:g}" if scale != 1 and not plot.get("unit_label") else "")
        if categorical:
            chart.xaxis.major_label_orientation = .8
        # Keep scenarios separate when the legend uses another dimension.
        series_keys = list(dict.fromkeys([series] + (["scenario"] if "scenario" not in panel_keys and x != "scenario" else [])))
        groups = list(panel.groupby(series_keys, sort=False, dropna=False, observed=True))
        rank = {name: i for i, name in enumerate(plot["series_order"])}
        groups.sort(key=lambda item: (rank.get(str((item[0] if isinstance(item[0], tuple) else (item[0],))[0]), 9999), str(item[0])))
        if len(groups) > series_limit:
            notes.append(f"Panel shows {series_limit} of {len(groups)} series; net dots are suppressed.")
        complete_series = len(groups) <= series_limit
        groups = groups[:series_limit]
        legend_columns = 3 if "ncols" in Legend.properties() else 1
        chart.height = 350 + ((len(groups) + (1 if stacked and plot["net_total"] else 0) + legend_columns - 1) // legend_columns) * 22
        pos, neg = np.zeros(len(xs)), np.zeros(len(xs))
        net = np.zeros(len(xs))
        absolute_net, baseline_net = np.zeros(len(xs)), np.zeros(len(xs))
        complete = np.ones(len(xs), dtype=bool)
        width = .8 if categorical else (min(np.diff([pd.Timestamp(v).value / 1e6 for v in xs])) * .8 if len(xs) > 1 else 86400000 * .8)
        for index, (key, group) in enumerate(groups):
            key = key if isinstance(key, tuple) else (key,)
            legend = " | ".join(str(v) for v in key)
            if group.duplicated(x).any():
                raise ValueError("Panel contains duplicate X/series measurements; select a facet or narrower filters.")
            group = group.set_index(x).reindex(xs)
            vals = group.value.to_numpy(dtype=float) * scale
            complete &= np.isfinite(vals)
            net += np.nan_to_num(vals)
            absolute_net += np.nan_to_num(group.absolute_value.to_numpy(dtype=float))
            baseline_net += np.nan_to_num(group.baseline_value.to_numpy(dtype=float))
            color = color_for(str(key[0]), plot["colors"])
            coords = labels if categorical else xs
            source = ColumnDataSource({"x": coords, "value": vals, "series": [legend] * len(xs),
                "absolute": group.absolute_value.tolist(), "baseline": group.baseline_value.tolist(),
                "model": group.model_name.fillna("").tolist(), "status": group.comparison_status.fillna("missing scenario").tolist()})
            if stacked:
                # Positive and negative contributions have separate baselines.
                lower = np.where(vals >= 0, pos, neg).copy()
                upper = lower + vals
                source.data.update(bottom=lower, top=upper)
                if plot["chart_type"] == "Stacked Bar":
                    chart.vbar(x="x", top="top", bottom="bottom", width=width, source=source, color=color, legend_label=legend)
                else:
                    chart.varea(x="x", y1="bottom", y2="top", source=source, color=color, alpha=.85, legend_label=legend)
                pos += np.where(vals > 0, vals, 0)
                neg += np.where(vals < 0, vals, 0)
            elif plot["chart_type"] == "Bar":
                if categorical:
                    source.data["x"] = [(v, (index - (len(groups)-1)/2) * .8 / len(groups)) for v in labels]
                else:
                    source.data["x"] = [pd.Timestamp(v).value / 1e6 + (index - (len(groups)-1)/2) * width / len(groups) for v in xs]
                chart.vbar(x="x", top="value", width=width / len(groups), source=source, color=color, legend_label=legend)
            else:
                if plot["chart_type"] in {"Line", "Dot-Line"}:
                    chart.line(x="x", y="value", source=source, color=color, line_width=2, legend_label=legend)
                if plot["chart_type"] in {"Dot", "Dot-Line"} or len(xs) == 1:
                    chart.scatter(x="x", y="value", source=source, color=color, size=5, legend_label=legend)
        if stacked and (~complete).any():
            # Hide incomplete stacks rather than suggesting a smaller total.
            for renderer in chart.renderers:
                for field in ("top", "bottom"):
                    if field in renderer.data_source.data:
                        renderer.data_source.data[field] = np.where(complete, renderer.data_source.data[field], np.nan)
            notes.append(f"{int((~complete).sum())} incomplete stack positions are hidden; inspect the comparison-status table.")
        if stacked and plot["net_total"] and complete_series:
            net_source = ColumnDataSource({"x": labels if categorical else xs, "y": np.where(complete, net, np.nan),
                "value": np.where(complete, net, np.nan), "absolute": np.where(complete, absolute_net, np.nan),
                "baseline": np.where(complete, baseline_net, np.nan) if plot["comparison"] != "Absolute" else [np.nan]*len(xs),
                "series": ["Net total"]*len(xs), "model": [", ".join(models)]*len(xs),
                "status": ["net of selected complete stack"]*len(xs)})
            chart.scatter(x="x", y="y", source=net_source, color="#222222", size=7, legend_label="Net total")
        chart.add_tools(HoverTool(tooltips=[("Series", "@series"), ("Value", "@value{0,0.000}"),
            (f"Absolute ({panel.unit.iloc[0]})", "@absolute{0,0.000}"), (f"Baseline ({panel.unit.iloc[0]})", "@baseline{0,0.000}"), ("Model", "@model"), ("Status", "@status")]))
        if groups:
            chart.legend.click_policy = "hide"
            chart.legend.label_text_font_size = "9px"
            legend = chart.legend[0]
            if legend_columns > 1:
                legend.ncols = legend_columns
            legend.spacing = 1
            legend.padding = 3
            chart.add_layout(legend, "below")
        finite = np.concatenate([pos, neg]) if stacked else panel.value.to_numpy(dtype=float) * scale
        finite = finite[np.isfinite(finite)]
        bounds.extend(finite.tolist())
        charts.append(chart)
    # Shared scales only within a single measurement identity; never across units/properties.
    if plot["shared_axes"] and charts and table.property_name.nunique() == 1 and table.unit.nunique() == 1 and table.collection_name.nunique() == 1 and bounds:
        low, high = min(0, min(bounds)), max(0, max(bounds))
        padding = (high - low) * .05 or 1
        shared = Range1d(low - padding, high + padding)
        for chart in charts:
            chart.y_range = shared
    return gridplot(charts, ncols=plot["columns"], sizing_mode="stretch_width", merge_tools=False), notes
