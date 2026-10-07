import json
import threading
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pxbp.cli import main
from pxbp.sources import Cancelled, LocalReader, Selection, Source, load_sources, stream_query


@pytest.fixture
def parquet(tmp_path):
    root = tmp_path / "solution with spaces"
    con = duckdb.connect()
    con.execute("CREATE TABLE keys (SeriesId INTEGER, ParentClassName VARCHAR, CollectionName VARCHAR, ChildClassName VARCHAR, ChildObjectName VARCHAR, ChildObjectCategoryName VARCHAR, PropertyName VARCHAR, PhaseName VARCHAR, PeriodTypeName VARCHAR, TimesliceName VARCHAR, SampleName VARCHAR, ModelName VARCHAR, UnitValue VARCHAR, BandId INTEGER)")
    con.execute("INSERT INTO keys VALUES (1,'System','Generators','Generator','Gas, LLC','Gas','Generation','ST','Day','All Periods','Mean','Model','MWh',1), (2,'System','Generators','Generator','Wind','Wind','Generation','ST','Day','All Periods','Mean','Model','MWh',1)")
    con.execute("CREATE TABLE vals (SeriesId INTEGER, PeriodId INTEGER, Value DOUBLE)")
    con.execute("INSERT INTO vals VALUES (1,1,2),(1,2,3),(2,1,5),(2,2,7)")
    con.execute("CREATE TABLE periods (PeriodId INTEGER, StartDate TIMESTAMP, EndDate TIMESTAMP)")
    con.execute("INSERT INTO periods VALUES (1,'2024-01-01','2024-01-02'),(2,'2024-01-02','2024-01-03')")
    for table, folder in (("keys", "fullkeyinfo"), ("vals", "data"), ("periods", "period")):
        (root / folder).mkdir(parents=True)
        con.execute("COPY " + table + " TO ? (FORMAT PARQUET)", [str(root / folder / "part.parquet")])
    con.close()
    return root


def selection(**kwargs):
    return Selection({"collection": "SystemGenerators", "properties": "Generation", "phase": "STSchedule",
                      "period": "Day", "timeslice": "All Periods", **kwargs}, batch_size=2)


def test_local_stream_direct_without_csv(parquet, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CSV export must not be invoked for local Parquet")
    monkeypatch.setattr("plexos_query.Solution.QueryToCSV", forbidden)
    monkeypatch.setattr("pxbp.sources.run_cli", forbidden)
    batches = list(stream_query([Source("Local", path=str(parquet))], selection()))
    assert [len(b.frame) for b in batches] == [2, 2]
    frame = pd.concat([batch.frame for batch in batches])
    assert sorted(frame.value.tolist()) == [2, 3, 5, 7]
    assert frame.source_kind.unique().tolist() == ["parquet"]
    assert frame.source_path.unique().tolist() == [str(parquet)]
    assert not list(parquet.rglob("*.csv"))


def test_local_filter_exact_object_and_aggregation(parquet):
    source = Source("Local", path=str(parquet))
    batches = list(stream_query([source], selection(child=["Gas, LLC"], date_from="2024-01-02")))
    assert batches[0].frame.value.tolist() == [3]
    batches = list(stream_query([source], selection(aggregate_by="object", aggregate_type="SUM")))
    assert sorted(pd.concat([b.frame for b in batches]).value.tolist()) == [7, 10]


def test_local_global_budget_cancel_schema(parquet, tmp_path):
    source = Source("Local", path=str(parquet))
    with pytest.raises(ValueError, match="Row limit exceeded"):
        list(stream_query([source, Source("B", path=str(parquet))], Selection(selection().query, max_rows=5, batch_size=2)))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        list(stream_query([source], selection(), cancel))
    with pytest.raises(ValueError, match="Missing"):
        list(stream_query([Source("Invalid", path=str(tmp_path))], selection()))


def test_local_config_paths_relative_to_file(parquet, tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{"label": "A", "path": parquet.name}]}))
    monkeypatch.chdir(tmp_path.parent)
    assert load_sources(config)[0].path == str(parquet)
    with pytest.raises(ValueError, match="exactly one"):
        Source("Invalid", solution_id="00000000-0000-0000-0000-000000000001", path=str(parquet))


def test_cli_local_json_stream(parquet, tmp_path, capsys):
    spec = tmp_path / "query.json"
    spec.write_text(json.dumps(selection().query))
    assert main(["--parquet", str(parquet), "query", "--selection", str(spec), "--batch-size", "2"]) == 0
    output = capsys.readouterr()
    assert not output.err
    assert [len(json.loads(line)) for line in output.out.splitlines()] == [2, 2]
