import pandas as pd
import pytest

from pxbp.annual_metrics import aggregate_metric, metric_rows, metrics_document, validate_metrics_spec


def spec(family="power", temporal="snapshot"):
    return {"years": [2031, 2032], "assets": [{"collection": "SystemGenerators", "object_name": "Plant A",
        "technology": "Gas-CC", "owner": "Current owner", "state": "AA", "planning_region": "North"}],
        "metrics": [{"id": "capacity", "title": "Installed capacity", "family": family, "temporal": temporal,
        "queries": [{"collection": "SystemGenerators", "properties": "Installed Capacity", "phase": "LTPlan", "period": "Year"}]}]}


def frame(unit="MW", value=1500, year=2031, name="Plant A"):
    return pd.DataFrame([dict(scenario="Case A", collection_name="Generators", object_name=name, property_name="Installed Capacity",
        period_type_name="Year", phase_name="LTPlan", timeslice_name="All Periods", sample_name="Mean", model_name="Model A",
        band_id=1, unit=unit, value=value, start_date=f"{year}-01-01")])


def test_installed_stock_requires_one_year():
    s = spec(); m = s["metrics"][0]
    rows = metric_rows(pd.concat([frame(), frame(year=2032, value=2000)]), s, m)
    with pytest.raises(ValueError, match="Snapshot"):
        aggregate_metric(rows, m, "planning_region", "All years")
    assert aggregate_metric(rows, m, "planning_region", "2032").value.tolist() == [2]


def test_currency_scale_and_energy_unit_rejection():
    s = spec("money", "sum"); m = s["metrics"][0]
    assert metric_rows(frame("$000", 1000000), s, m).value.tolist() == [1]
    s = spec(); m = s["metrics"][0]
    with pytest.raises(ValueError, match="power unit"):
        metric_rows(frame("MWh"), s, m)


def test_unmapped_nonzero_remains_visible():
    s = spec(); rows = metric_rows(frame(name="New plant"), s, s["metrics"][0])
    assert rows.iloc[0]["value"] == 1.5
    assert rows.iloc[0]["owner"] == "Unassigned"
    assert rows.iloc[0]["mapping_status"] == "unmapped"


def test_duplicate_band_and_mixed_samples_fail():
    s = spec(); m = s["metrics"][0]
    duplicate = pd.concat([frame(), frame()])
    with pytest.raises(ValueError, match="Multiple rows"):
        metric_rows(duplicate, s, m)
    other = frame(name="Plant B"); other["sample_name"] = "Draw 1"
    with pytest.raises(ValueError, match="Mixed annual"):
        metric_rows(pd.concat([frame(), other]), s, m)


def test_ratio_keeps_object_identity():
    s = spec("percent"); m = s["metrics"][0]; rows = metric_rows(frame("%", 15), s, m)
    with pytest.raises(ValueError, match="individual objects"):
        aggregate_metric(rows, m, "planning_region", "2031")
    assert aggregate_metric(rows, m, "object_name", "2031").value.tolist() == [15]


def test_sector_costs_do_not_include_generation_twice():
    s = spec("money", "sum"); m = s["metrics"][0]
    s["assets"].append({"collection": "SystemGenerators", "object_name": "Upgrade", "sector": "Flowgate", "technology": "Flowgate"})
    m["sectors"] = ["Flowgate"]
    rows = metric_rows(pd.concat([frame("$000", 2e6), frame("$000", 3e6, name="Upgrade")]), s, m)
    assert rows.object_name.tolist() == ["Upgrade"]
    assert rows.value.tolist() == [3]


def test_snapshot_dashboard_has_no_all_years_option():
    from bokeh.models import Select
    s = spec(); m = s["metrics"][0]; rows = metric_rows(frame(), s, m)
    document = metrics_document({m["id"]: rows}, [{"metric": "capacity", "status": "reported"}], s, ["Case A"])
    selectors = list(document.select({"type": Select}))
    years = next(control for control in selectors if control.title == "Year")
    assert years.options == ["2031", "2032"]
    assert years.value == "2032"


def test_unsupported_technology_fails_before_rendering():
    s = spec(); s["assets"][0]["technology"] = "Unrecognized"
    with pytest.raises(ValueError, match="color identity"):
        validate_metrics_spec(s)


def test_mapped_upgrade_label_retains_source_identity():
    s = spec("money", "sum"); m = s["metrics"][0]
    s["assets"][0]["report_object_name"] = "Gate A"
    m["object_label"] = "mapped"
    rows = metric_rows(frame("$000", 5000), s, m)
    assert rows.iloc[0]["object_name"] == "Gate A"
    assert rows.iloc[0]["source_object_name"] == "Plant A"
    del s["assets"][0]["report_object_name"]
    with pytest.raises(ValueError, match="explicit report_object_name"):
        metric_rows(frame("$000", 5000), s, m)


def test_native_units_are_not_reinterpreted_as_power():
    s = spec("native"); m = s["metrics"][0]
    rows = metric_rows(frame("-", 500), s, m)
    assert rows.unit.tolist() == ["-"]
    assert rows.value.tolist() == [500]
    with pytest.raises(ValueError, match="mixes units"):
        metric_rows(pd.concat([frame("-"), frame("MW", year=2032)]), s, m)


def test_pdf_retains_zonal_values_and_technology_colors(tmp_path):
    from pxbp.annual_metrics import write_metrics_pdf
    s = spec(); m = s["metrics"][0]; rows = metric_rows(frame(), s, m)
    output = tmp_path/"report.pdf"
    write_metrics_pdf(output, {m["id"]: rows}, s, ["Case A"])
    assert output.read_bytes().startswith(b"%PDF")
    m.update(asset_detail=True, geographies=["object_name"])
    write_metrics_pdf(tmp_path/"zonal.pdf", {m["id"]: rows}, s, ["Case A"])


def test_stock_cannot_be_declared_as_an_annual_flow():
    s = spec("power", "sum")
    with pytest.raises(ValueError, match="snapshot temporal"):
        validate_metrics_spec(s)
    s = spec()
    with pytest.raises(ValueError, match="nonnegative"):
        metric_rows(frame(value=-100), s, s["metrics"][0])


def test_cost_component_queries_cannot_double_count_one_collection():
    s = spec("money", "sum"); m = s["metrics"][0]
    m["queries"][0]["properties"] = "Total Cost"
    m["queries"].append({**m["queries"][0], "properties": "Build Cost"})
    with pytest.raises(ValueError, match="one property per collection"):
        validate_metrics_spec(s)


def test_ratio_collection_retains_assets_without_detail_flag(monkeypatch):
    from types import SimpleNamespace
    import pxbp.annual_metrics as module
    s = spec("percent"); m = s["metrics"][0]
    reported = pd.concat([frame("%", 15), frame("%", 25, name="Plant B")], ignore_index=True)
    monkeypatch.setattr(module, "stream_query", lambda *args, **kwargs: iter([SimpleNamespace(frame=reported)]))
    data, coverage = module.collect_metrics([SimpleNamespace(label="Case A", path=None)], s)
    assert set(data[m["id"]].object_name) == {"Plant A", "Plant B"}
    assert data[m["id"]].value.sum() == 40
    assert next(c for c in coverage if c["year"]==2032)["status"] == "not reported"
