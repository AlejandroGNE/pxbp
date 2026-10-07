import csv
import json
import sys
import threading
from pathlib import Path

import pytest

from pxbp.sources import Cancelled, CloudReader, Selection, Source, load_sources, run_cli, stream_query

UUID = "00000000-0000-0000-0000-000000000001"


def fake_cli(command, cancel, timeout):
    if "--output-file" in command:
        sql = Path(command[command.index("--sql-file") + 1]).read_text()
        limit = int(sql.rsplit("LIMIT ", 1)[1])
        path = Path(command[command.index("--output-file") + 1])
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["start_date", "end_date", "value", "object_name", "unit"])
            writer.writeheader()
            for row in range(min(3, limit)):
                writer.writerow({"start_date": "2024-01-01", "value": row + 1,
                                 "end_date": "2024-01-02", "object_name": "Wind, LLC", "unit": "MWh"})
        return ""
    return json.dumps([{"ParentClassName": "System", "CollectionName": "Generators"}])


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setattr("pxbp.sources.run_cli", fake_cli)
    monkeypatch.setattr("plexos_query.cloud_cli.shutil.which", lambda value: "plexos-cloud")
    return Source("Baseline", UUID)


def test_two_sources_batch_and_provenance(cloud):
    batches = list(stream_query([cloud, Source("Alternative", UUID)],
                   Selection({"collection": "SystemGenerators", "properties": "Generation"}, batch_size=2)))
    assert [len(batch.frame) for batch in batches] == [2, 1, 2, 1]
    assert batches[0].frame.object_name.tolist() == ["Wind, LLC"] * 2
    assert batches[-1].frame.scenario.tolist() == ["Alternative"]


def test_global_limit_is_not_silent(cloud):
    with pytest.raises(ValueError, match="Row limit exceeded"):
        list(stream_query([cloud, Source("Alternative", UUID)],
             Selection({"collection": "SystemGenerators", "properties": "Generation"}, max_rows=4, batch_size=2)))


def test_cancelled_before_request(cloud):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        list(stream_query([cloud], Selection({"collection": "SystemGenerators", "properties": "Generation"}), cancel))


def test_window_boundaries_and_period_aggregation():
    spec = Selection({"collection": "SystemGenerators", "properties": "Generation",
                      "date_from": "2024-01-01", "date_to": "2024-01-03"}, window_days=1)
    windows = list(spec.windows())
    assert len(windows) == 3
    assert windows[0][1] == windows[1][0]
    with pytest.raises(ValueError, match="Period aggregation"):
        Selection(dict(spec.query, aggregate_by="period"), window_days=1)
    with pytest.raises(ValueError, match="Unknown query fields"):
        Selection(dict(spec.query, typo="x"))


def test_run_cli_error_timeout_and_cancel():
    with pytest.raises(RuntimeError, match="intentional failure"):
        run_cli([sys.executable, "-c", "import sys; sys.stderr.write('intentional failure'); sys.exit(4)"], threading.Event(), 10)
    with pytest.raises(TimeoutError):
        run_cli([sys.executable, "-c", "import time; time.sleep(10)"], threading.Event(), 0.2)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        run_cli([sys.executable, "-c", "import time; time.sleep(10)"], cancel, 10)


def test_sources_reject_duplicate_labels(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [{"label": "a", "solution_id": UUID}] * 2}))
    with pytest.raises(ValueError, match="unique"):
        load_sources(path)
