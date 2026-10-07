"""Pivot shared long-form results without mixing units or reported series choices."""
from __future__ import annotations

import pandas as pd

IDENTITY = ["property_name", "unit", "phase_name", "period_type_name", "timeslice_name",
            "sample_name", "model_name", "band_id"]
AXES = ["start_date", "year", "month", "day", "hour", "object_name", "category_name", "scenario"]
SERIES = ["scenario", "category_name", "object_name", "property_name", "unit", "timeslice_name"]


def pivot(frame, *, x="start_date", series="scenario", operation="sum", filters=None):
    if x not in AXES or series not in SERIES or operation not in {"sum", "mean", "min", "max"}:
        raise ValueError("Unsupported pivot axis, series, or operation")
    data = frame.copy()
    for key, values in (filters or {}).items():
        if key not in data.columns:
            raise ValueError(f"Unknown filter: {key}")
        data = data[data[key].isin(values)]
    for part in ("year", "month", "day", "hour"):
        data[part] = getattr(data["start_date"].dt, part)
    keys = list(dict.fromkeys([x, series, "scenario"] + IDENTITY))
    return data.groupby(keys, dropna=False, observed=True, as_index=False)["value"].agg(operation)


def chart_series(table, x, series):
    """Full metadata identity remains visible in separate legend series."""
    dimensions = [c for c in table.columns if c not in {x, "value"}]
    varying = [c for c in dimensions if table[c].nunique(dropna=False) > 1]
    labels = list(dict.fromkeys([series, "scenario", "unit"] + varying))
    labels = [c for c in labels if c != x and c in table]
    for _, group in table.groupby(dimensions, dropna=False, observed=True, sort=False):
        title = " | ".join(f"{c}: {group[c].iloc[0]}" for c in labels if str(group[c].iloc[0]))
        yield title or "Values", group.sort_values(x)
