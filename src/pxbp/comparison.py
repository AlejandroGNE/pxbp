"""Align aggregated scenario measurements with an explicitly chosen baseline."""
from __future__ import annotations

import numpy as np
import pandas as pd

MODES = ["Absolute", "Difference", "Percent change", "Ratio"]


def compare(table, baseline, mode="Absolute", *, visible=None):
    """Compare after aggregation; absent measurements never become implicit zeros.

    Model names are provenance, not cross-solution join keys. One model must be
    selected per scenario, preventing accidental sums across different models.
    All remaining dimensions (including units and samples) are exact join keys.
    """
    if mode not in MODES:
        raise ValueError("Unsupported comparison mode")
    result = table.copy()
    result["absolute_value"] = result["value"]
    if mode == "Absolute":
        result["baseline_value"] = np.nan
        result["comparison_status"] = np.where(result.value.notna(), "absolute", "undefined metric")
        return result if visible is None else result[result.scenario.isin(visible)]
    if baseline not in set(table.scenario):
        raise ValueError("The baseline is not loaded. Include it in the query.")
    if table.groupby("scenario", dropna=False).model_name.nunique(dropna=False).gt(1).any():
        raise ValueError("Baseline comparison requires one reported model per scenario; filter models first.")
    keys = [c for c in table if c not in {"scenario", "model_name", "value"}]
    base = table[table.scenario == baseline][keys + ["value", "model_name"]].rename(
        columns={"value": "baseline_value", "model_name": "baseline_model_name"})
    if base.duplicated(keys).any():
        raise ValueError("Baseline has duplicate measurement identities")
    # Outer alignment preserves categories/dates absent from either side.
    aligned = []
    for scenario, frame in table.groupby("scenario", sort=False, dropna=False):
        merged = frame.merge(base, on=keys, how="outer", validate="one_to_one", indicator=True)
        merged["scenario"] = scenario
        merged["model_name"] = merged.model_name.fillna(frame.model_name.iloc[0])
        merged["absolute_value"] = merged["value"]
        merged["comparison_status"] = merged["_merge"].astype(str).map(
            {"both": "matched", "left_only": "missing baseline", "right_only": "missing scenario"})
        matched = merged.comparison_status.eq("matched")
        merged.loc[matched & merged.value.isna(), "comparison_status"] = "undefined scenario"
        merged.loc[matched & merged.baseline_value.isna(), "comparison_status"] = "undefined baseline"
        matched = merged.comparison_status.eq("matched")
        delta = merged["value"] - merged.baseline_value
        if mode == "Difference":
            merged["value"] = delta.where(matched)
        else:
            nonzero = merged.baseline_value.ne(0)
            merged.loc[matched & ~nonzero, "comparison_status"] = "zero baseline"
            merged["value"] = (100 * delta / merged.baseline_value if mode == "Percent change"
                               else merged.absolute_value / merged.baseline_value).where(matched & nonzero)
        merged["value"] = merged["value"].replace([np.inf, -np.inf], np.nan)
        aligned.append(merged.drop(columns="_merge"))
    result = pd.concat(aligned, ignore_index=True)
    return result if visible is None else result[result.scenario.isin(visible)]
