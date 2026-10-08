import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from pxbp.cli import main
from pxbp.reports import TECHNOLOGY_COLORS, capacity_rows, collect_capacity, load_spec
from pxbp.sources import load_sources


@pytest.fixture
def demo(tmp_path):
    module_path = Path(__file__).parents[1] / "examples" / "create-capacity-demo.py"
    module_spec = importlib.util.spec_from_file_location("capacity_demo", module_path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    folder = module.create_demo(tmp_path / "demo")
    return folder, load_sources(folder / "sources.json"), load_spec(folder / "capacity-spec.json")


def row(**extra):
    return {"scenario": "Case", "collection_name": "Generators", "object_name": "Asset", "start_date": "2030-01-01",
            "property_name": "Units Built", "period_type_name": "Year", "unit": "-", "value": .5, **extra}


def spec(**extra):
    return {"assets": [{"collection": "SystemGenerators", "object_name": "Asset", "region": "Region A",
                        "technology": "UPV", "capacity_mw": 1000, **extra}]}


def test_count_to_mw_year_rating_and_direct_gw():
    rows, _ = capacity_rows(pd.DataFrame([row()]), spec())
    assert rows.capacity_mw.tolist() == [500]
    rows, _ = capacity_rows(pd.DataFrame([row()]), spec(capacity_mw_by_year={"2030": 200}))
    assert rows.capacity_mw.tolist() == [100]
    rows, _ = capacity_rows(pd.DataFrame([row(property_name="Capacity Built", unit="GW", value=2)]), spec())
    assert rows.capacity_mw.tolist() == [2000]


def test_exclusions_and_missing_mapping():
    rows, excluded = capacity_rows(pd.DataFrame([row()]), spec(exclude_reason="Infrastructure proxy"))
    assert rows.empty and excluded[0]["reason"] == "Infrastructure proxy"
    with pytest.raises(ValueError, match="no asset mapping"):
        capacity_rows(pd.DataFrame([row(object_name="Unknown")]), spec())
    with pytest.raises(ValueError, match="requires an audited"):
        capacity_rows(pd.DataFrame([row()]), spec(capacity_mw=None))
    with pytest.raises(ValueError, match="energy units"):
        capacity_rows(pd.DataFrame([row(property_name="Capacity Built", unit="MWh")]), spec())


def test_duplicate_and_mixed_sample_rejected():
    with pytest.raises(ValueError, match="Multiple rows"):
        capacity_rows(pd.DataFrame([row(), row(sample_name="Another")]), spec())
    with pytest.raises(ValueError, match="Mixed"):
        capacity_rows(pd.DataFrame([row(sample_name="Mean"), row(start_date="2031-01-01", sample_name="Another")]), spec())


def test_real_adapter_annual_totals_and_pdf_export(demo, tmp_path):
    folder, sources, report_spec = demo
    rows, excluded, years = collect_capacity(sources, report_spec)
    # 9 units solar * 200 + 4.5 units wind * 150 + 1.5 units battery * 100.
    assert rows[rows.scenario == "Case A"].capacity_mw.sum() == 2625
    assert rows[rows.scenario == "Case B"].capacity_mw.sum() == 3281.25
    assert years == [2030, 2031, 2032] and len(excluded) == 6
    output = tmp_path / "report"
    assert main(["--config", str(folder / "sources.json"), "report", "--spec", str(folder / "capacity-spec.json"), "--output", str(output)]) == 0
    audit = json.loads((output / "audit.json").read_text())
    assert audit["technology_colors"] == TECHNOLOGY_COLORS
    assert (output / "capacity.pdf").read_bytes().startswith(b"%PDF-")
    assert "#FFC903" in (output / "capacity.html").read_text(encoding="utf-8")
    assert main(["--config", str(folder / "sources.json"), "report", "--spec", str(folder / "capacity-spec.json"), "--output", str(output)]) == 2


def test_spec_rejects_cumulative_or_aggregated_builds(demo):
    folder, _, value = demo
    value["queries"][0]["properties"] = "NetNewCapacity"
    target = folder / "invalid.json"
    target.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Capacity additions require"):
        load_spec(target)
