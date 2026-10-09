import threading
import time

import pandas as pd
from bokeh.document import Document

from pxbp.app import make_document
from pxbp.pivot import chart_series, pivot
from pxbp.sources import Source, normalize

SOURCE = Source("A", "00000000-0000-0000-0000-000000000001")


def data():
    return normalize([{"start_date": "2024-01-01", "value": 2, "unit": "MWh", "property_name": "Generation"},
                      {"start_date": "2024-01-01", "value": 3, "unit": "MWh", "property_name": "Generation"},
                      {"start_date": "2024-01-01", "value": 10, "unit": "USD", "property_name": "Cost"},
                      {"start_date": "2024-02-01", "value": 4, "unit": "MWh", "property_name": "Generation"}], SOURCE)


def test_pivot_keeps_units_properties_and_dates_separate():
    table = pivot(data())
    assert sorted(table.value.tolist()) == [4, 5, 10]
    assert len(list(chart_series(table, "start_date", "scenario"))) == 2
    assert pivot(data(), x="month").month.tolist() == [1, 1, 2]
    filtered = pivot(data(), filters={"unit": ["MWh"]}, operation="mean")
    assert sorted(filtered.value.tolist()) == [2.5, 4]


def test_bokeh_document_and_render():
    doc = Document()
    app = make_document(doc, [SOURCE])
    assert app.tabs.active == 0
    app.frame = data()
    app.render()
    assert len(app.chart.children) == 1
    assert len(app.table_source.data["value"]) == 3
    doc.validate()
    doc.to_json()
    app.frame = data().head(3)
    app.render()
    for chart, _, _ in app.chart.children[0].children:
        assert chart.x_range.end > chart.x_range.start
    app.chart_type.value = "Bar"
    app.x.value = "month"
    doc.validate()


def test_worker_completion_and_cancellation():
    app = make_document(Document(), [SOURCE])
    app.start_job(lambda cancel, emit: emit("metadata", {"choices": ["Generation"]}))
    for _ in range(100):
        app.pump()
        if app.job is None:
            break
        time.sleep(0.01)
    assert app.job is None and not app.run_button.disabled
    assert "Generation" in app.metadata.text

    def work(cancel, emit):
        cancel.wait(3)
        emit("metadata", {})

    app.start_job(work)
    app.cancel()
    for _ in range(100):
        app.pump()
        if app.job is None:
            break
        time.sleep(0.01)
    assert app.job is None
    assert "cancelled" in app.status.text
