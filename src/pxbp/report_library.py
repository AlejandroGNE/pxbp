"""Curated annual measurements with explicit scope, units, and aggregation rules."""
from __future__ import annotations

from copy import deepcopy
import re

from .sources import Selection
from .workspace import PLOT_DEFAULTS


def _preset(title, collection, object_class, prop, family, *, objects=False, stacked=True, note=""):
    return {"title": title, "collection": collection, "class": object_class, "property": prop,
        "family": family, "query": {"collection": collection, "parent": "System", "properties": list(dict.fromkeys([prop, prop.replace(" ", "")])),
            "phase": "LTPlan", "period": "Year", "timeslice": "All Periods", "sample": "Mean", "band_id": 1,
            "aggregate_by": "none"},
        "plot": {"x": "year", "series": "object_name" if objects and stacked else "scenario" if objects else "category_name",
            "facet": "scenario" if stacked else "object_name", "chart_type": "Stacked Bar" if stacked else "Dot-Line",
            "net_total": stacked, "operation": "sum", "columns": 1}, "note": note}


PRESETS = {
    "annual-generation": _preset("Annual generation", "SystemGenerators", "Generator", "Generation", "energy"),
    "installed-capacity": _preset("Installed generator capacity", "SystemGenerators", "Generator", "Installed Capacity", "power",
        note="Annual reported capacity, not a sum of capacity over the horizon."),
    "new-capacity": _preset("New generator capacity", "SystemGenerators", "Generator", "Capacity Built", "power"),
    "battery-power": _preset("Battery power capacity", "SystemBatteries", "Battery", "Generation Capacity", "power", objects=True),
    "battery-energy": _preset("Battery energy capacity", "SystemBatteries", "Battery", "Installed Capacity", "storage-energy", objects=True),
    "new-battery-power": _preset("New battery power capacity", "SystemBatteries", "Battery", "Generation Capacity Built", "power", objects=True),
    "new-battery-energy": _preset("New battery energy capacity", "SystemBatteries", "Battery", "Capacity Built", "storage-energy", objects=True),
    "battery-discharge": _preset("Battery discharge energy", "SystemBatteries", "Battery", "Generation", "energy", objects=True),
    "battery-charge": _preset("Battery charging energy", "SystemBatteries", "Battery", "Load", "energy", objects=True),
    "emissions": _preset("Reported emissions", "SystemEmissions", "Emission", "Production", "native", objects=True, stacked=False,
        note="Emission objects remain separate. Reported mass units are preserved; no tonne convention is inferred."),
    "curtailment": _preset("Generation curtailed", "SystemRegions", "Region", "Generation Curtailed", "energy", objects=True, stacked=False,
        note="Region objects remain separate; overlapping regional totals are not added."),
    "system-cost": _preset("Reported total system cost", "SystemRegions", "Region", "Total System Cost", "money", objects=True, stacked=False,
        note="Reported annual cost, with no added build costs, inferred discounting, or currency conversion."),
    "generation-cost": _preset("Reported total generation cost", "SystemRegions", "Region", "Total Generation Cost", "money", objects=True, stacked=False,
        note="Reported regional generation cost; do not add to total system cost."),
    "generator-total-cost": _preset("Reported generator total cost", "SystemGenerators", "Generator", "Total Cost", "money",
        note="A separate reported measure; not a decomposition of system cost."),
    "generator-build-cost": _preset("Generator build cost", "SystemGenerators", "Generator", "Build Cost", "money",
        note="Reported build cost; not added to other reported total-cost measures."),
}
DEFAULT_SECTIONS = ["annual-generation", "installed-capacity", "new-capacity", "battery-power", "battery-energy", "emissions", "curtailment", "system-cost", "generation-cost"]
FAMILIES = {"power": ({"MW": .001, "GW": 1.0}, "GW"),
            "energy": ({"MWh": 1e-6, "GWh": .001, "TWh": 1.0}, "TWh"),
            "storage-energy": ({"MWh": .001, "GWh": 1.0}, "GWh"),
            "money": ({"$": 1e-9, "$000": 1e-6}, "$B (reported)")}
FILTERS = {"phase", "period", "timeslice", "sample", "model", "band_id", "date_from", "date_to", "child", "category", "parent"}
COMMON_FILTERS = FILTERS - {"period", "child", "category", "parent"}


def compact(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def get_preset(preset_id):
    if preset_id not in PRESETS:
        raise ValueError(f"Unknown annual report preset: {preset_id}")
    return deepcopy(PRESETS[preset_id])


def preset_query(preset_id, filters=None):
    definition = get_preset(preset_id)
    filters = filters or {}
    if not isinstance(filters, dict) or set(filters) - FILTERS:
        raise ValueError("Annual query filters contain unsupported fields")
    query = {**definition["query"], **filters}
    if compact(query.get("period")) not in {"year", "fiscalyear", "4"}:
        raise ValueError("Annual report presets require Year or FiscalYear; interval values cannot substitute")
    if query.get("timeslice") in (None, "", []) or query.get("sample") in (None, "", []) or "band_id" not in query:
        raise ValueError("Annual reports need explicit time slice, sample, and band choices")
    Selection(query)
    return query


def preset_plot(preset_id, baseline, labels, overrides=None):
    from .workspace import validate_plot
    overrides = overrides or {}
    plot = {**PLOT_DEFAULTS, **get_preset(preset_id)["plot"], "baseline": baseline, **overrides}
    if plot["x"] != "year" or plot["operation"] != "sum":
        raise ValueError("Annual presets preserve annual years and sum only distinct assets; use the custom pivot for other calculations")
    definition = get_preset(preset_id)
    if not definition["plot"]["net_total"] and (plot["series"] != "scenario" or plot["facet"] != "object_name"):
        raise ValueError("This preset must preserve individual region or emission objects")
    if plot["scale"] != 1 or plot["unit_label"]:
        raise ValueError("Annual presets already convert units; custom display scaling would change those units")
    return validate_plot(plot, labels)


def prepare_annual(frame, preset_id):
    """Validate raw asset/year rows, then normalize aliases and convert units once."""
    definition = get_preset(preset_id)
    data = frame.copy()
    if data.empty:
        return data
    if not data.class_name.map(compact).eq(compact(definition["class"])).all():
        raise ValueError("Reported class does not match this preset")
    if not data.property_name.map(compact).eq(compact(definition["property"])).all():
        raise ValueError("Reported property does not match this preset")
    if not data.period_type_name.map(compact).isin(["year", "fiscalyear"]).all():
        raise ValueError("Annual report contains non-annual measurements")
    # A single asset/year choice is required before adding assets to categories.
    identity = ["scenario", "collection_name", "object_name", "phase_name", "sample_name", "model_name", "band_id", "timeslice_name"]
    years = data.start_date.dt.year
    if data.assign(_year=years).duplicated(identity + ["_year"]).any():
        raise ValueError("Duplicate asset/year measurements or property aliases; choose one reported series")
    if data.groupby("scenario").model_name.nunique(dropna=False).gt(1).any():
        raise ValueError("Annual presets require one reported model per scenario")
    for name in ("property_name", "unit", "value", "phase_name", "period_type_name", "collection_name"):
        data["reported_" + name] = data[name]
    family = definition["family"]
    if family != "native":
        factors, unit = FAMILIES[family]
        unknown = set(data.unit) - set(factors)
        if unknown:
            raise ValueError(f"Unexpected annual {family} unit(s): {', '.join(sorted(unknown))}")
        data["value"] = data.value * data.unit.map(factors)
        data["unit"] = unit
    else:
        # A unit is part of measurement identity; multiple units never form a stack.
        if data.groupby("object_name").unit.nunique().gt(1).any():
            raise ValueError("An emission object reports different mass units across sources; select consistent units")
    data["property_name"] = definition["property"]
    data["collection_name"] = definition["collection"]
    data["phase_name"] = data.phase_name.replace({"LTPlan": "LT", "STSchedule": "ST"})
    data["period_type_name"] = "Year"
    return data
