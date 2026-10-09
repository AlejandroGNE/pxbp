import importlib.util
import json
import threading
import time
from pathlib import Path

import pandas as pd
import pytest
from bokeh.document import Document

from pxbp.app import make_document
from pxbp.bundles import build_bundle, export_bundle, make_bundle, offline_layout, read_bundle, validate_bundle
from pxbp.report_library import PRESETS, prepare_annual, preset_query
from pxbp.sources import Cancelled, Source, normalize


@pytest.fixture
def demo(tmp_path):
    path=Path(__file__).parents[1]/"examples/create-report-library-demo.py"
    spec=importlib.util.spec_from_file_location("report_demo",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.create_demo(tmp_path/"demo",cases=2)


def raw(unit="MW",prop="InstalledCapacity",**kwargs):
    return normalize([{"start_date":"2030-01-01","end_date":"2031-01-01","object_name":"Asset",
        "class_name":"Generator","collection_name":"Generators","property_name":prop,"period_type_name":"Year",
        "phase_name":"LT","sample_name":"Mean","timeslice_name":"All Periods","model_name":"Model","band_id":1,
        "category_name":"Gas-CC","unit":unit,"value":1000,**kwargs}],Source("Baseline",path="unused"))


def test_library_converts_once_and_preserves_raw_provenance():
    frame=prepare_annual(raw(),"installed-capacity")
    assert frame.value.tolist()==[1]
    assert frame.unit.tolist()==["GW"]
    assert frame.reported_unit.tolist()==["MW"]
    assert frame.reported_value.tolist()==[1000]
    assert frame.property_name.tolist()==["Installed Capacity"]
    with pytest.raises(ValueError,match="Unexpected"):
        prepare_annual(raw(unit="MWh"),"installed-capacity")
    with pytest.raises(ValueError,match="non-annual"):
        prepare_annual(raw(period_type_name="Interval"),"installed-capacity")
    with pytest.raises(ValueError,match="Duplicate asset/year"):
        prepare_annual(pd.concat([raw(),raw(start_date="2030-06-01")]),"installed-capacity")
    with pytest.raises(ValueError,match="one reported model"):
        prepare_annual(pd.concat([raw(),raw(object_name="Second",model_name="Other")]),"installed-capacity")


def test_query_rules_and_bundle_validation(demo):
    with pytest.raises(ValueError,match="require Year"):
        preset_query("annual-generation",{"period":"Interval"})
    with pytest.raises(ValueError,match="unsupported"):
        preset_query("system-cost",{"properties":"Build Cost"})
    sources,config=read_bundle(demo)
    for change,match in (({"baseline":"Unknown"},"baseline"),({"sections":[{"id":"../bad","preset":"annual-generation"}]},"Section IDs"),
        ({"sections":[{"id":"a","preset":"curtailment","plot":{"facet":"None"}}]},"individual"),
        ({"query_filters":[]},"query_filters")):
        with pytest.raises(ValueError,match=match):validate_bundle({**config,**change})


def test_real_adapter_bundle_deltas_scopes_and_offline_serialization(demo,tmp_path):
    _,config=read_bundle(demo)
    result=build_bundle(config,tmp_path/"cache")
    assert len(result["sections"])==9
    assert all(r["status"]=="complete" for r in result["sections"])
    for section in result["sections"]:
        delta=section["views"]["Difference"]["table"]
        assert delta[delta.scenario=="Baseline"].value.eq(0).all()
        assert delta.comparison_status.eq("matched").all()
        case=delta[delta.scenario=="Case 01"]
        assert (case.value > 0).all()
    region=next(r for r in result["sections"] if r["section"]["preset"]=="system-cost")
    assert set(region["views"]["Absolute"]["table"].object_name)=={"Inner region","Outer region"}
    assert set(region["views"]["Absolute"]["table"].unit)=={"$B (reported)"}
    battery=next(r for r in result["sections"] if r["section"]["preset"]=="battery-energy")
    assert set(battery["views"]["Absolute"]["table"].unit)=={"GWh"}
    document=Document();document.add_root(offline_layout(result));document.validate();document.to_json()


def test_unavailable_preset_is_explicit_and_not_zero(demo,tmp_path):
    _,config=read_bundle(demo)
    config["sections"]=[{"id":"generation","preset":"annual-generation","query_filters":{"child":["Unreported"]}}]
    result=build_bundle(config)
    assert result["sections"][0]["status"]=="unavailable"
    assert all(c["status"]=="unavailable" for c in result["sections"][0]["coverage"])
    assert not result["sections"][0]["views"]
    cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):build_bundle(config,cancel=cancel)
    _,full=read_bundle(demo)
    with pytest.raises(ValueError,match="Row limit|budget"):
        build_bundle(full,max_rows=1)


def test_live_report_and_bundle_configs(demo,tmp_path):
    sources,config=read_bundle(demo)
    app=make_document(Document(),sources,bundle=config,cache_dir=tmp_path/"cache")
    assert app.tabs.active==4 and app.job is None and app.bundle_result is None
    config["query_filters"]={"sample":"Mean", "model":["Baseline","Case 01"], "band_id":1}
    app.apply_bundle(config)
    app.save_bundle()
    assert json.loads(app.bundle_text.value)==config
    app.report_choice.value="installed-capacity";app.apply_report()
    assert app.active_report=="installed-capacity"
    assert json.loads(app.extra.value)["model"]==["Baseline","Case 01"]
    assert app.period.value=="Year" and app.aggregation.value=="none"
    app.save_workspace()
    saved=json.loads(app.config_text.value)
    assert saved["report_preset"]=="installed-capacity"
    app.apply_workspace(saved)
    assert app.active_report=="installed-capacity"
    app.doc.validate();app.doc.to_json()
    app.run()
    for _ in range(400):
        app.pump()
        if app.job is None:break
        time.sleep(.01)
    assert app.job is None and app.complete
    assert set(app.frame.unit)=={"GW"}
    app.bundle_sections.value=["annual-generation","system-cost"]
    app.run_bundle()
    for _ in range(600):
        app.pump()
        if app.job is None:break
        time.sleep(.01)
    assert app.job is None and app.bundle_result
    assert len(app.bundle_result["sections"])==2
    assert "2/2" in app.bundle_status.text


def test_bundle_export_html_pdf_and_audit(demo,tmp_path):
    output=export_bundle(demo,tmp_path/"output")
    assert (output/"reports.html").stat().st_size>10000
    assert (output/"reports.pdf").read_bytes().startswith(b"%PDF")
    manifest=json.loads((output/"complete.json").read_text())
    assert manifest["all_sections_available"]
    audit=json.loads((output/"audit.json").read_text())
    assert len(audit["sections"])==9
    assert len(list(output.glob("*-raw.parquet")))==9
    with pytest.raises(ValueError,match="already exists"):
        export_bundle(demo,output)


def test_missing_baseline_retains_absolute_and_flags_delta(demo,tmp_path):
    _,config=read_bundle(demo)
    config["sections"]=[{"id":"generation","preset":"annual-generation"}]
    config["query_filters"]={"model":["Case 01"]}
    result=build_bundle(config)
    section=result["sections"][0]
    assert section["status"]=="partial"
    assert section["views"]["Absolute"]["status"]=="available"
    assert section["views"]["Difference"]["status"]=="unavailable"
    assert section["coverage"][0]["status"]=="unavailable"
    spec=tmp_path/"partial.private.json";spec.write_text(json.dumps(config))
    output=export_bundle(spec,tmp_path/"partial")
    assert not json.loads((output/"complete.json").read_text())["all_sections_available"]
    assert not (output/"generation-difference.parquet").exists()


def test_annual_workspace_snapshot_matches_live_units(demo,tmp_path):
    from pxbp.snapshot import export_snapshot
    sources,_=read_bundle(demo)
    app=make_document(Document(),sources)
    app.report_choice.value="installed-capacity";app.apply_report();app.save_workspace()
    config=tmp_path/"workspace.private.json";config.write_text(app.config_text.value)
    output=export_snapshot(config,tmp_path/"snapshot")
    import duckdb
    with duckdb.connect() as con:
        table=con.execute("SELECT * FROM read_parquet(?)",[str(output/"comparison.parquet")]).fetchdf()
    assert set(table.unit)=={"GW"}
    assert table.value.max()<2
