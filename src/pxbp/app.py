"""Bokeh session UI. Workers communicate through a bounded queue; only callbacks edit models."""
from __future__ import annotations

import html
import json
import queue
import threading

import pandas as pd
from bokeh.layouts import column, row
from bokeh.models import (Button, ColumnDataSource, DataTable, Div, MultiChoice,
                          Select, Spinner, TableColumn, TextAreaInput, TextInput)
from bokeh.palettes import Category20
from bokeh.plotting import figure

from .pivot import AXES, SERIES, chart_series, pivot
from .sources import COLUMNS, Cancelled, Selection, reader_for, stream_query


class PivotApp:
    def __init__(self, doc, sources):
        self.doc, self.sources = doc, sources
        self.frame = pd.DataFrame(columns=COLUMNS)
        self.job = None
        self.query_count = 0
        self.status = Div(text="Choose reported query choices, then run. No queries run automatically.")
        self.source_choice = MultiChoice(title="Solutions to query", options=[s.label for s in sources],
                                         value=[s.label for s in sources])
        self.collection = TextInput(title="Collection", value="SystemGenerators")
        self.properties = TextInput(title="Properties (comma separated)", value="Generation")
        self.phase = TextInput(title="Phase", value="STSchedule")
        self.period = TextInput(title="Period", value="Interval")
        self.timeslice = TextInput(title="Time slice (blank = all)", value="All Periods")
        self.child = TextAreaInput(title="Objects (one exact name per line; blank = all)", rows=3)
        self.date_from = TextInput(title="From (ISO timestamp; inclusive)")
        self.date_to = TextInput(title="Through (ISO timestamp; inclusive)")
        self.aggregation = Select(title="Query aggregation", value="category",
                                  options=["none", "category", "object", "period"])
        self.aggregate_type = Select(title="Query operation", value="SUM", options=["SUM", "AVERAGE", "MIN", "MAX"])
        self.extra = TextAreaInput(title="Extra query filters (JSON: sample, model, category, parent, filter)", value="{}", rows=3)
        self.max_rows = Spinner(title="Maximum rows across all solutions", low=1, high=1000000, step=10000, value=100000)
        self.window_days = Spinner(title="Cloud window days (0 = one request; requires both dates)", low=0, high=366, value=0)
        self.run_button = Button(label="Run query", button_type="primary")
        self.explore_button = Button(label="Explore collection in first selected solution")
        self.cancel_button = Button(label="Cancel", disabled=True)
        self.x = Select(title="X axis", value="start_date", options=AXES)
        self.series = Select(title="Series", value="scenario", options=SERIES)
        self.operation = Select(title="Pivot operation", value="sum", options=["sum", "mean", "min", "max"])
        self.chart_type = Select(title="Chart", value="Line", options=["Line", "Bar"])
        self.filters = {name: MultiChoice(title=f"Filter {name} (empty = all)", options=[])
                        for name in ("scenario", "category_name", "object_name", "timeslice_name")}
        self.chart = column()
        self.table_source = ColumnDataSource(data={"x": [], "series": [], "unit": [], "value": []})
        self.table = DataTable(source=self.table_source, columns=[TableColumn(field=c, title=c)
                               for c in ("x", "series", "unit", "value")], height=250, sizing_mode="stretch_width")
        self.pivot_note = Div(text="")
        self.metadata = Div(text="")
        for widget in [self.x, self.series, self.operation, self.chart_type, *self.filters.values()]:
            widget.on_change("value", self._pivot_changed)
        self.run_button.on_click(self.run)
        self.explore_button.on_click(self.explore)
        self.cancel_button.on_click(self.cancel)
        controls = column(Div(text="<h2>PLEXOS Bokeh Pivot</h2>"), self.source_choice,
                          self.collection, self.properties, row(self.phase, self.period), self.timeslice,
                          self.child, row(self.date_from, self.date_to),
                          row(self.aggregation, self.aggregate_type), self.extra,
                          self.max_rows, self.window_days, self.run_button, self.explore_button,
                          self.cancel_button, width=480)
        results = column(self.status, row(self.x, self.series, self.operation, self.chart_type),
                         row(*self.filters.values()), self.pivot_note, self.chart, self.table,
                         self.metadata, sizing_mode="stretch_width")
        doc.add_root(row(controls, results, sizing_mode="stretch_width"))
        doc.title = "PLEXOS Bokeh Pivot"
        doc.add_periodic_callback(self.pump, 150)
        doc.on_session_destroyed(lambda context: self.cancel())

    def selected_sources(self):
        sources = [s for s in self.sources if s.label in self.source_choice.value]
        if not sources:
            raise ValueError("Select at least one solution")
        return sources

    def selection(self):
        query = {"collection": self.collection.value.strip(), "properties": self.properties.value.strip(),
                 "phase": self.phase.value.strip(), "period": self.period.value.strip(),
                 "timeslice": self.timeslice.value.strip(), "date_from": self.date_from.value.strip(),
                 "date_to": self.date_to.value.strip(), "aggregate_by": self.aggregation.value}
        if self.aggregation.value != "none":
            query["aggregate_type"] = self.aggregate_type.value
        children = [s.strip() for s in self.child.value.splitlines() if s.strip()]
        if children:
            query["child"] = children
        extra = json.loads(self.extra.value)
        if not isinstance(extra, dict) or set(extra) - {"sample", "model", "category", "parent", "filter"}:
            raise ValueError("Extra filters support only sample, model, category, parent, filter")
        query.update(extra)
        query = {k: v for k, v in query.items() if v not in (None, "", [])}
        return Selection(query, max_rows=int(self.max_rows.value), window_days=int(self.window_days.value))

    def start_job(self, work):
        if self.job is not None:
            return
        cancel, events = threading.Event(), queue.Queue(maxsize=4)
        self.job = (cancel, events)
        self.run_button.disabled = self.explore_button.disabled = True
        self.cancel_button.disabled = False

        def emit(kind, value):
            while not cancel.is_set():
                try:
                    events.put((kind, value), timeout=0.1)
                    return
                except queue.Full:
                    pass
            raise Cancelled("Query cancelled")

        def worker():
            try:
                work(cancel, emit)
                emit("done", "Complete")
            except Exception as exc:
                # Cancellation must unblock a full queue; discard queued partial batches.
                if cancel.is_set():
                    while True:
                        try:
                            events.get_nowait()
                        except queue.Empty:
                            break
                events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="pxbp-query").start()

    def run(self):
        if self.job is not None:
            return
        try:
            selection, sources = self.selection(), self.selected_sources()
        except Exception as exc:
            self.status.text = "Cannot run: " + html.escape(str(exc))
            return
        self.frame = pd.DataFrame(columns=COLUMNS)
        self.query_count = 0
        self.metadata.text = ""
        self.chart.children = []
        self.table_source.data = {"x": [], "series": [], "unit": [], "value": []}
        self.pivot_note.text = ""
        self.status.text = "Querying selected solutions…"

        def work(cancel, emit):
            for batch in stream_query(sources, selection, cancel):
                emit("batch", batch)

        self.start_job(work)

    def explore(self):
        if self.job is not None:
            return
        try:
            source = self.selected_sources()[0]
        except ValueError as exc:
            self.status.text = html.escape(str(exc))
            return
        collection = self.collection.value.strip()
        self.status.text = "Exploring reported choices…"

        def work(cancel, emit):
            info = reader_for(source, cancel, 180).explore(collection)
            emit("metadata", info)

        self.start_job(work)

    def cancel(self):
        if self.job:
            self.job[0].set()

    def pump(self):
        if not self.job:
            return
        _, events = self.job
        changed = False
        # Bound callback work so a fast producer cannot monopolize the document.
        for _ in range(4):
            try:
                kind, value = events.get_nowait()
            except queue.Empty:
                break
            if kind == "batch":
                self.frame = value.frame.copy() if self.frame.empty else pd.concat([self.frame, value.frame], ignore_index=True)
                self.query_count += len(value.frame)
                self.status.text = f"Received {self.query_count:,} rows; latest scenario: {html.escape(value.source.label)}. Results are provisional."
                changed = True
            elif kind == "metadata":
                self.metadata.text = "<pre>" + html.escape(json.dumps(value, indent=2, default=str)) + "</pre>"
            else:
                prefix = "Complete" if kind == "done" else "Stopped; query results may be incomplete"
                self.status.text = prefix + ": " + html.escape(str(value)) + f". {self.query_count:,} rows."
                self.job = None
                self.run_button.disabled = self.explore_button.disabled = False
                self.cancel_button.disabled = True
                break
        if changed:
            for name, widget in self.filters.items():
                widget.options = sorted(set(self.frame[name]) - {""})
            self.render()

    def _pivot_changed(self, attr, old, new):
        self.render()

    def render(self):
        if self.frame.empty:
            return
        filters = {name: widget.value for name, widget in self.filters.items() if widget.value}
        table = pivot(self.frame, x=self.x.value, series=self.series.value,
                      operation=self.operation.value, filters=filters)
        groups = list(chart_series(table, self.x.value, self.series.value))
        categorical = self.x.value != "start_date"
        kwargs = {"x_range": sorted({str(v) for v in table[self.x.value]})} if categorical else {"x_axis_type": "datetime"}
        plot = figure(height=420, sizing_mode="stretch_width", tools="pan,wheel_zoom,box_zoom,reset,save", **kwargs)
        plot.xaxis.axis_label = self.x.value
        plot.yaxis.axis_label = f"value ({self.operation.value})"
        colors = Category20[20]
        for index, (label, group) in enumerate(groups[:100]):
            xs = group[self.x.value].astype(str).tolist() if categorical else group[self.x.value].tolist()
            source = ColumnDataSource({"x": xs, "value": group["value"].tolist()})
            if self.chart_type.value == "Bar":
                width = 0.8 if categorical else 3600000 * 0.8
                plot.vbar(x="x", top="value", source=source, width=width, color=colors[index % 20], legend_label=label)
            else:
                plot.line(x="x", y="value", source=source, line_width=2, color=colors[index % 20], legend_label=label)
                plot.scatter(x="x", y="value", source=source, size=4, color=colors[index % 20], legend_label=label)
        if groups:
            plot.legend.click_policy = "hide"
        self.chart.children = [plot]
        preview = table.head(1000)
        self.table_source.data = {"x": preview[self.x.value].astype(str).tolist(),
                                  "series": preview[self.series.value].astype(str).tolist(),
                                  "unit": preview["unit"].tolist(), "value": preview["value"].tolist()}
        self.pivot_note.text = (f"{len(table):,} pivot rows; table shows first 1,000; chart shows first 100 of {len(groups):,} series. "
                                "Property, unit, phase, period, time slice, sample, model and band remain separate. "
                                "Year/month/day/hour axes combine repeated dates using the selected operation.")


def make_document(doc, sources):
    return PivotApp(doc, sources)
