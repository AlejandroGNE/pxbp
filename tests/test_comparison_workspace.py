import json
import threading

import duckdb
import pandas as pd
import pytest
from bokeh.document import Document
from bokeh.models import GlyphRenderer, Scatter

from pxbp.app import make_document
from pxbp.cache import query_cached
from pxbp.comparison import compare
from pxbp.pivot import pivot
from pxbp.plotting import build_charts, color_for
from pxbp.sources import Cancelled, Selection, Source, normalize
from pxbp.workspace import PLOT_DEFAULTS, PRESETS, make_workspace, read_workspace


def measurements():
    frames = []
    for label, values in (("Base", [10, 0]), ("Alternative", [7, 2])):
        source = Source(label, path="unused")
        frames.append(normalize([{"start_date": "2030-01-01", "end_date": "2031-01-01",
            "collection_name": "Generators", "class_name": "Generator", "property_name": "Generation",
            "unit": "GWh", "category_name": tech, "model_name": label + " Model", "value": value}
            for tech, value in zip(("Gas-CC", "UPV"), values)], source))
    return pd.concat(frames, ignore_index=True)


def table(frame=None):
    return pivot(measurements() if frame is None else frame, x="year", series="category_name")


def test_deltas_preserve_models_and_hidden_baseline():
    delta = compare(table(), "Base", "Difference", visible=["Alternative"])
    assert delta.value.tolist() == [-3, 2]
    assert set(delta.model_name) == {"Alternative Model"}
    assert set(delta.baseline_model_name) == {"Base Model"}
    pct = compare(table(), "Base", "Percent change", visible=["Alternative"])
    assert pct.iloc[0].value == -30
    assert pd.isna(pct.iloc[1].value)
    assert pct.iloc[1].comparison_status == "zero baseline"
    ratio = compare(table(), "Base", "Ratio", visible=["Alternative"])
    assert ratio.iloc[0].value == .7


def test_absent_measurements_never_become_zero():
    frame = measurements()
    frame = frame[~((frame.scenario == "Base") & (frame.category_name == "UPV"))]
    frame.loc[(frame.scenario == "Alternative") & (frame.category_name == "Gas-CC"), "unit"] = "MWh"
    delta = compare(table(frame), "Base", "Difference", visible=["Alternative"])
    assert delta.value.isna().all()
    assert set(delta.comparison_status) == {"missing baseline", "missing scenario"}
    with pytest.raises(ValueError, match="not loaded"):
        compare(table(), "Unknown", "Difference")
    two_models = pd.concat([measurements(), measurements().assign(model_name="Another")])
    with pytest.raises(ValueError, match="one reported model"):
        compare(table(two_models), "Base", "Difference")


def test_signed_stacks_and_net_dot():
    delta = compare(table(), "Base", "Difference", visible=["Alternative"])
    plot = {**PLOT_DEFAULTS, **PRESETS["Scenario stacks"], "comparison": "Difference", "baseline": "Base"}
    grid, notes = build_charts(delta, plot)
    chart = grid.children[0][0]
    bars = [r for r in chart.renderers if isinstance(r, GlyphRenderer) and r.glyph.__class__.__name__ == "VBar"]
    assert {tuple(r.data_source.data["top"]) for r in bars} == {(-3,), (2,)}
    assert all(list(r.data_source.data["bottom"]) == [0] for r in bars)
    dot = next(r for r in chart.renderers if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Scatter))
    assert list(dot.data_source.data["y"]) == [-1]
    assert color_for("UPV", {}) == "#FFC903"
    assert color_for("Gas-CC", {}) == "#5E1688"
    assert color_for("Other asset", {}) == color_for("Other asset", {})
    with pytest.raises(ValueError, match="cannot be stacked"):
        build_charts(delta, {**plot, "comparison": "Percent change"})


def test_config_roundtrip_and_no_query_on_load(tmp_path):
    sources = [Source("Base", path=str(tmp_path)), Source("Alternative", path=str(tmp_path))]
    query = {"collection": "SystemGenerators", "properties": "Generation", "phase": "LTPlan", "period": "Year", "sample": "0", "band_id": 1}
    config = make_workspace(sources, query, {**PRESETS["Scenario stacks"], "comparison": "Difference", "baseline": "Base", "colors": {"Gas": "#123456"}})
    path = tmp_path / "workspace.json"
    path.write_text(json.dumps(config))
    _, saved = read_workspace(path)
    app = make_document(Document(), sources, workspace=saved)
    assert app.query_count == 0 and app.job is None
    assert app.chart_type.value == "Stacked Bar"
    app.save_workspace()
    assert json.loads(app.config_text.value) == config
    app.frame = measurements()
    app.complete = True
    app.render()
    assert "Cannot draw" not in str(app.chart.children)
    app.doc.validate()
    app.doc.to_json()
    bad = {**config, "plot": {**config["plot"], "colors": {"Gas": "red"}}}
    with pytest.raises(ValueError, match="six-digit"):
        app.apply_workspace(bad)
    assert app.baseline.value == "Base"


def test_completed_query_cache_and_global_budget(tmp_path, monkeypatch):
    source = Source("Base", path=str(tmp_path / "data"))
    selection = Selection({"collection": "Generators", "properties": "Generation"}, batch_size=1)
    calls = []

    class Reader:
        def rows(self, selection, remaining):
            calls.append(1)
            yield measurements().query("scenario == 'Base'")

    monkeypatch.setattr("pxbp.cache.reader_for", lambda *args: Reader())
    cache = tmp_path / "cache"
    assert sum(len(b.frame) for b in query_cached([source], selection, cache)) == 2
    assert sum(len(b.frame) for b in query_cached([source], selection, cache)) == 2
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Row limit"):
        list(query_cached([source], Selection(selection.query, max_rows=1), cache))
    list(query_cached([source], selection, cache, refresh=True))
    assert len(calls) == 2
    cancel = threading.Event(); cancel.set()
    with pytest.raises(Cancelled):
        list(query_cached([source], selection, cache, cancel))


def test_failed_queries_not_cached(tmp_path, monkeypatch):
    class Reader:
        def rows(self, selection, remaining):
            yield measurements().head(1)
            raise ValueError("incomplete")
    monkeypatch.setattr("pxbp.cache.reader_for", lambda *args: Reader())
    with pytest.raises(ValueError, match="incomplete"):
        list(query_cached([Source("Base", path="unused")], Selection({"collection": "Generators", "properties": "Generation"}), tmp_path))
    assert not list(tmp_path.iterdir())


def test_facet_preserves_categories_and_separates_units():
    data = measurements()
    data.loc[data.category_name == "UPV", "unit"] = "MWh"
    result = compare(pivot(data, x="year", series="scenario", facet="category_name"), "Base")
    grid, _ = build_charts(result, {**PLOT_DEFAULTS, **PRESETS["Technology comparisons"]})
    assert len(grid.children) == 2


def test_all_chart_types_serialize():
    from pxbp.workspace import CHART_TYPES
    result = compare(table(), "Base", "Difference")
    for kind in CHART_TYPES:
        plot = {**PLOT_DEFAULTS, **PRESETS["Scenario stacks"], "comparison": "Difference", "baseline": "Base", "chart_type": kind}
        grid, notes = build_charts(result, plot)
        doc = Document(); doc.add_root(grid)
        doc.validate(); doc.to_json()


def test_relative_workspace_sources_and_invalid_inputs(tmp_path):
    config = make_workspace([Source("Base", path="relative")], {"collection":"Generators", "properties":"Generation"}, {})
    path = tmp_path / "workspace.json"; path.write_text(json.dumps(config))
    sources, resolved = read_workspace(path)
    assert sources[0].path == str(tmp_path / "relative")
    assert resolved["sources"][0]["path"] == sources[0].path
    app = make_document(Document(), sources, workspace=resolved)
    assert app.sources[0].path == sources[0].path
    with pytest.raises(ValueError, match="band_id"):
        Selection({"collection":"Generators", "properties":"Generation", "band_id":True})


def test_bulk_36_synthetic_solutions_and_discovery(tmp_path):
    import importlib.util
    from pathlib import Path
    from pxbp.discovery import discover_sources
    module_path = Path(__file__).parents[1] / "examples/create-pivot-demo.py"
    spec = importlib.util.spec_from_file_location("pivot_demo", module_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    workspace_path = module.create_demo(tmp_path / "demo")
    sources, workspace = read_workspace(workspace_path)
    discovered, metadata = discover_sources(tmp_path / "demo")
    assert len(sources) == len(discovered) == 36
    assert metadata[0]["models"] == ["Baseline"]
    selection = Selection(workspace["query"])
    frame = pd.concat([b.frame for b in query_cached(sources, selection, tmp_path / "cache")])
    assert len(frame) == 540
    delta = compare(pivot(frame, x="year", series="category_name"), "Baseline", "Difference")
    assert delta.comparison_status.eq("matched").all()
    assert delta.groupby(["scenario","year"]).value.sum().eq(0).all()
    assert delta[(delta.scenario == "Case 01") & (delta.category_name == "Gas-CC")].value.tolist() == [-3,-6,-9,-12,-15]
    grid, notes = build_charts(delta, workspace["plot"])
    assert len(grid.children) == 36 and not notes


def test_cached_input_changes_invalidate_key(tmp_path):
    from pxbp.cache import cache_key
    root = tmp_path / "solution"; root.mkdir()
    file = root / "part.parquet"; file.write_bytes(b"before")
    source = Source("Base",path=str(root))
    selection = Selection({"collection":"Generators","properties":"Generation"})
    before = cache_key(source, selection)
    file.write_bytes(b"after data changes")
    assert cache_key(source, selection) != before


def test_percent_and_ratio_ignore_physical_unit_display_scale():
    result = compare(table(), "Base", "Percent change", visible=["Alternative"])
    grid, _ = build_charts(result, {**PLOT_DEFAULTS, **PRESETS["Technology comparisons"],
        "comparison":"Percent change", "baseline":"Base", "scale":.001, "unit_label":"TWh"})
    chart = grid.children[0][0]
    renderer = next(r for r in chart.renderers if isinstance(r, GlyphRenderer))
    assert list(renderer.data_source.data["value"]) == [-30]
    assert chart.yaxis[0].axis_label == "Percent change (%)"
