"""Bokeh session UI. Workers communicate through a bounded queue; only callbacks edit models."""
from __future__ import annotations

import base64
import html
import json
import queue
import threading

import pandas as pd
from bokeh.layouts import column, row
from bokeh.models import (Button, ColumnDataSource, DataTable, Div, MultiChoice,
                          Select, Spinner, TabPanel, Tabs, TableColumn, TextAreaInput, TextInput, CheckboxGroup, CustomJS, FileInput)

from .pivot import AXES, SERIES, pivot
from .sources import COLUMNS, Cancelled, Selection, Source, reader_for
from .comparison import MODES, compare
from .cache import query_cached
from .plotting import build_charts
from .workspace import CHART_TYPES, PRESETS, make_workspace, validate_plot
from .report_library import PRESETS as REPORT_PRESETS, DEFAULT_SECTIONS, COMMON_FILTERS as REPORT_FILTERS, preset_query, preset_plot, prepare_annual
from .bundles import build_bundle, make_bundle, validate_bundle, section_layout


class PivotApp:
    def __init__(self, doc, sources, *, workspace=None, cache_dir=None, bundle=None, analysis=None):
        self.doc, self.sources = doc, sources
        self.cache_dir = cache_dir
        self.active_report = None
        self.bundle_result = None
        self.bundle_configuration = bundle
        self.bundle_loading = False
        self.complete = True
        self.loading_config = False
        self.plot_overrides = {"colors": {}, "series_order": [], "scale": 1.0, "unit_label": ""}
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
        self.extra = TextAreaInput(title="Extra query filters (JSON: sample, model, category, parent, filter, band_id)", value="{}", rows=3)
        self.max_rows = Spinner(title="Maximum rows across all solutions", low=1, high=1000000, step=10000, value=100000)
        self.window_days = Spinner(title="Cloud window days (0 = one request; requires both dates)", low=0, high=366, value=0)
        self.report_choice = Select(title="Annual report preset", value="custom", options=[("custom", "Custom query"), *[(k,v["title"]) for k,v in REPORT_PRESETS.items()]], width=400)
        self.apply_report_button = Button(label="Apply report preset")
        self.apply_report_button.on_click(self.apply_report)
        self.report_note = Div(text="Choose an annual report to fill its query, units, and plot settings.", width=400)
        self.run_button = Button(label="Run query", button_type="primary")
        self.explore_button = Button(label="Explore collection")
        self.cancel_button = Button(label="Cancel", disabled=True)
        self.x = Select(title="X axis", value="start_date", options=AXES)
        self.series = Select(title="Series", value="scenario", options=SERIES)
        self.operation = Select(title="Pivot operation", value="sum", options=["sum", "mean", "min", "max"])
        self.chart_type = Select(title="Chart", value="Line", options=CHART_TYPES)
        self.baseline = Select(title="Baseline", value=sources[0].label, options=[s.label for s in sources])
        self.comparison = Select(title="Show", value="Absolute", options=MODES)
        self.facet = Select(title="One panel per", value="None", options=["None", *SERIES])
        self.preset = Select(title="View preset", value="Custom", options=["Custom", *PRESETS])
        self.columns = Spinner(title="Panels per row", low=1, high=6, value=3, step=1)
        self.display_options = CheckboxGroup(labels=["Net-total dots on stacks", "Share Y scale"], active=[1])
        self.cache_options = CheckboxGroup(labels=["Reuse complete cached queries"], active=[0])
        self.config_text = TextAreaInput(title="Workspace configuration (contains source paths/IDs)", rows=15, sizing_mode="stretch_width")
        self.load_button = Button(label="Apply displayed configuration")
        self.save_button = Button(label="Prepare current configuration", button_type="primary")
        self.download_button = Button(label="Download displayed configuration")
        self.config_file = FileInput(accept=".json")
        self.config_status = Div(text="Apply or open a saved JSON workspace. Press Run query to load its data.")
        self.save_button.on_click(self.save_workspace)
        self.load_button.on_click(self.load_workspace)
        self.config_file.on_change("value", self._config_uploaded)
        self.download_button.js_on_click(CustomJS(args={"text": self.config_text}, code="""
            if (!text.value.trim()) return;
            const blob = new Blob([text.value], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = 'workspace.private.json';
            a.click(); URL.revokeObjectURL(url);
        """))
        self.preset.on_change("value", self._preset_changed)
        self.bundle_sections = MultiChoice(title="Reports to include", options=[(k,v["title"]) for k,v in REPORT_PRESETS.items()], value=DEFAULT_SECTIONS, width=600)
        self.bundle_max_rows = Spinner(title="Maximum rows across all report sections and solutions", low=1, high=1000000, value=1000000, step=10000, width=400)
        self.bundle_baseline = Select(title="Shared report baseline", options=[s.label for s in sources], value=sources[0].label, width=400)
        self.build_bundle_button = Button(label="Build report bundle", button_type="primary")
        self.build_bundle_button.on_click(self.run_bundle)
        self.bundle_section = Select(title="Display report section", options=[], value="", width=400)
        self.bundle_scenarios = MultiChoice(title="Scenarios to display (empty = all queried)", options=[s.label for s in sources], value=[], width=600)
        self.bundle_section.on_change("value", self._bundle_view_changed)
        self.bundle_scenarios.on_change("value", self._bundle_view_changed)
        self.bundle_chart = column(Div(text="Choose reports and build the bundle."), sizing_mode="stretch_width")
        self.bundle_text = TextAreaInput(title="Report bundle configuration (private source paths/IDs)", rows=10, sizing_mode="stretch_width")
        self.bundle_save = Button(label="Prepare report configuration")
        self.bundle_apply = Button(label="Apply report configuration")
        self.bundle_download = Button(label="Download report configuration")
        self.bundle_file = FileInput(accept=".json")
        self.bundle_save.on_click(self.save_bundle)
        self.bundle_apply.on_click(self.load_bundle)
        self.bundle_file.on_change("value", self._bundle_uploaded)
        self.bundle_download.js_on_click(CustomJS(args={"text": self.bundle_text}, code="""
            if (!text.value.trim()) return;
            const url = URL.createObjectURL(new Blob([text.value], {type:'application/json'}));
            const a = document.createElement('a'); a.href=url; a.download='bundle.private.json'; a.click(); URL.revokeObjectURL(url);
        """))
        self.bundle_status = Div(text="One baseline applies to every report section. No queries run until you build.")
        self.filters = {name: MultiChoice(title=f"Filter {name} (empty = all)", options=[])
                        for name in ("scenario", "category_name", "object_name", "timeslice_name", "property_name", "unit")}
        self.chart = column(Div(text="Run a query to view its pivot."), sizing_mode="stretch_width")
        self.table_source = ColumnDataSource(data={"x": [], "series": [], "unit": [], "value": []})
        self.table = DataTable(source=self.table_source, columns=[TableColumn(field=c, title=c)
                               for c in ("x", "series", "unit", "value", "absolute_value", "baseline_value", "comparison_status", "model_name")], height=250, sizing_mode="stretch_width")
        self.pivot_note = Div(text="")
        self.metadata = Div(text="")
        for widget in [self.x, self.series, self.operation, self.chart_type, self.baseline, self.comparison, self.facet, self.columns, *self.filters.values()]:
            widget.on_change("value", self._pivot_changed)
        self.display_options.on_change("active", self._pivot_changed)
        self.run_button.on_click(self.run)
        self.explore_button.on_click(self.explore)
        self.cancel_button.on_click(self.cancel)
        for widget in [self.phase, self.period, self.date_from, self.date_to, self.aggregation, self.aggregate_type]:
            widget.width = 195
        for widget in [self.source_choice, self.collection, self.properties, self.timeslice,
                       self.child, self.extra, self.max_rows, self.window_days]:
            widget.width = 400
        for widget in [self.x, self.series, self.operation, self.chart_type]:
            widget.width = 195
        for widget in self.filters.values():
            widget.width = 195
        controls = column(self.source_choice, self.report_choice, self.apply_report_button, self.report_note,
                          self.collection, self.properties, row(self.phase, self.period), self.timeslice,
                          self.child, row(self.date_from, self.date_to),
                          row(self.aggregation, self.aggregate_type), self.extra,
                          self.max_rows, self.window_days, self.cache_options,
                          Div(text="Explore checks the first selected solution. Blank optional filters select all reported choices."),
                          width=410)
        filters = list(self.filters.values())
        results = column(self.preset, row(self.comparison, self.baseline),
                         row(self.x, self.series), row(self.operation, self.chart_type),
                         row(self.facet, self.columns), self.display_options,
                         row(*filters[:2]), row(*filters[2:4]), row(*filters[4:]), self.pivot_note, self.chart, self.table,
                         sizing_mode="stretch_width")
        from .analytics_ui import AnalyticsPanel
        self.analytics = AnalyticsPanel(self, analysis)
        self.tabs = Tabs(tabs=[TabPanel(title="Query", child=controls),
                              TabPanel(title="Pivot", child=results),
                              TabPanel(title="Reported choices", child=self.metadata),
                              TabPanel(title="Workspace", child=column(self.config_status, self.config_file,
                                  row(self.save_button, self.download_button), self.config_text, self.load_button, sizing_mode="stretch_width")),
                              TabPanel(title="Reports", child=column(self.bundle_status, self.bundle_sections, self.bundle_baseline, self.bundle_max_rows,
                                  self.build_bundle_button, self.bundle_section, self.bundle_scenarios, self.bundle_chart,
                                  Div(text="Save or edit the section order, plot settings, source list, and annual query filters below."),
                                  self.bundle_file, row(self.bundle_save, self.bundle_download, self.bundle_apply), self.bundle_text, sizing_mode="stretch_width")),
                              TabPanel(title="Analytics", child=self.analytics.layout)], sizing_mode="stretch_width")
        doc.add_root(column(Div(text="<h2>PLEXOS Bokeh Pivot</h2>"),
                            row(self.run_button, self.explore_button, self.cancel_button), self.status,
                            self.tabs, sizing_mode="stretch_width"))
        doc.title = "PLEXOS Bokeh Pivot"
        doc.add_periodic_callback(self.pump, 150)
        doc.on_session_destroyed(lambda context: self.cancel())
        if workspace:
            self.apply_workspace(workspace)
        if bundle:
            self.apply_bundle(bundle)
            self.tabs.active = 4
        if analysis:
            self.tabs.active = 5

    def selected_sources(self):
        sources = [s for s in self.sources if s.label in self.source_choice.value]
        if not sources:
            raise ValueError("Select at least one solution")
        if self.comparison.value != "Absolute":
            baseline = next((s for s in self.sources if s.label == self.baseline.value), None)
            if baseline and baseline not in sources:
                sources.insert(0, baseline)
        return sources

    def plot_config(self):
        return {**self.plot_overrides, "x": self.x.value, "series": self.series.value,
            "operation": self.operation.value, "chart_type": self.chart_type.value,
            "facet": self.facet.value, "comparison": self.comparison.value,
            "baseline": self.baseline.value, "columns": int(self.columns.value),
            "net_total": 0 in self.display_options.active, "shared_axes": 1 in self.display_options.active,
            "filters": {k: w.value for k, w in self.filters.items() if w.value}}

    def save_workspace(self):
        try:
            config = make_workspace(self.sources, self.selection().query,
                self.plot_config(), [s.label for s in self.selected_sources()])
            if self.active_report:
                config["report_preset"] = self.active_report
            self.config_text.value = json.dumps(config, indent=2)
            self.config_status.text = "Ready to download. This configuration includes private source paths or IDs."
        except Exception as exc:
            self.config_status.text = "Cannot save: " + html.escape(str(exc))

    def load_workspace(self):
        if self.job:
            self.config_status.text = "Wait for the current query to finish before loading a workspace."
            return
        try:
            self.apply_workspace(json.loads(self.config_text.value))
        except Exception as exc:
            self.config_status.text = "Cannot load: " + html.escape(str(exc))

    def _config_uploaded(self, attr, old, new):
        if new:
            try:
                self.config_text.value = base64.b64decode(new).decode("utf-8-sig")
                self.load_workspace()
            except Exception as exc:
                self.config_status.text = "Cannot read configuration: " + html.escape(str(exc))

    def apply_workspace(self, config):
        if not isinstance(config, dict) or config.get("version") != 1 or set(config) - {"version", "sources", "query", "plot", "selected_sources", "report_preset"}:
            raise ValueError("Expected a version 1 workspace")
        if not isinstance(config.get("sources"), list) or any(not isinstance(item, dict) or
            set(item) not in ({"label", "path"}, {"label", "solution_id"}) for item in config["sources"]):
            raise ValueError("Sources need label and exactly one of path or solution_id")
        sources = [Source(**item) for item in config["sources"]]
        labels = [s.label for s in sources]
        if not labels or len(set(labels)) != len(labels):
            raise ValueError("Use unique nonempty source labels")
        report_id = config.get("report_preset")
        if report_id and report_id not in REPORT_PRESETS:
            raise ValueError("Unknown saved annual preset")
        query = Selection(config["query"]).query
        plot = validate_plot(config.get("plot", {}), labels)
        selected = config.get("selected_sources", labels)
        if not isinstance(selected, list) or not selected or any(not isinstance(s, str) for s in selected) or set(selected) - set(labels):
            raise ValueError("Selected sources must name configured solutions")
        if plot["comparison"] != "Absolute" and plot["baseline"] not in selected:
            raise ValueError("Selected sources must include the baseline")
        # Validate every setting before editing widgets; loading runs no query.
        if query.get("aggregate_by", "none") not in self.aggregation.options or query.get("aggregate_type", "SUM").upper() not in self.aggregate_type.options:
            raise ValueError("Workspace query aggregation is not supported by this viewer")
        self.loading_config = True
        try:
            self.sources = sources
            self.active_report = report_id
            self.report_choice.value = report_id or "custom"
            self.bundle_baseline.options = labels
            self.bundle_baseline.value = plot["baseline"] or labels[0]
            self.bundle_scenarios.options = labels
            self.bundle_configuration = None
            self.source_choice.options = labels
            self.source_choice.value = selected
            self.baseline.options = labels
            for name in ("collection", "phase", "period", "timeslice", "date_from", "date_to"):
                getattr(self, name).value = str(query.get(name, ""))
            props = query["properties"]
            self.properties.value = ",".join(map(str, props)) if isinstance(props, list) else str(props)
            children = query.get("child", [])
            self.child.value = "\n".join(map(str, children)) if isinstance(children, list) else str(children)
            self.aggregation.value = query.get("aggregate_by", "none")
            self.aggregate_type.value = query.get("aggregate_type", "SUM").upper()
            self.extra.value = json.dumps({k: v for k, v in query.items() if k in {"sample", "model", "category", "parent", "filter", "band_id"}})
            for name in ("x", "series", "operation", "chart_type", "facet", "comparison", "baseline", "columns"):
                getattr(self, name).value = plot[name] or labels[0]
            self.display_options.active = ([0] if plot["net_total"] else []) + ([1] if plot["shared_axes"] else [])
            self.plot_overrides = {k: plot[k] for k in ("colors", "series_order", "scale", "unit_label")}
            for name, widget in self.filters.items():
                widget.options = list(plot["filters"].get(name, []))
                widget.value = plot["filters"].get(name, [])
            self.frame = pd.DataFrame(columns=COLUMNS)
            self.chart.children = [Div(text="Workspace loaded. Press Run query.")]
            self.table_source.data = {c: [] for c in ("x", "series", "unit", "value")}
            self.config_status.text = "Workspace loaded. Press Run query; no data was fetched automatically."
        finally:
            self.loading_config = False

    def apply_report(self):
        if self.job:
            return
        identifier = self.report_choice.value
        if identifier == "custom":
            self.active_report = None
            self.report_note.text = "Custom query: reported units are preserved without library conversions."
            return
        try:
            extra = json.loads(self.extra.value)
            filters = {k:v for k,v in (self.bundle_configuration or {}).get("query_filters", {}).items() if k in REPORT_FILTERS}
            filters.update({k:v for k,v in extra.items() if k in REPORT_FILTERS})
            if self.phase.value in {"LT", "LTPlan"}:
                filters["phase"] = self.phase.value
            filters.update({k:v for k,v in {"date_from":self.date_from.value, "date_to":self.date_to.value, "timeslice":self.timeslice.value}.items() if v})
            query = preset_query(identifier, filters)
            plot = preset_plot(identifier, self.baseline.value, [s.label for s in self.sources],
                {"colors":self.plot_overrides["colors"], "series_order":self.plot_overrides["series_order"], "comparison":self.comparison.value})
            if plot["comparison"] in {"Ratio", "Percent change"}:
                plot["chart_type"] = "Dot-Line"
                plot["net_total"] = False
            config = make_workspace(self.sources, query, plot, [s.label for s in self.selected_sources()])
            config["report_preset"] = identifier
            self.apply_workspace(config)
            self.report_note.text = f"{REPORT_PRESETS[identifier]['title']}: annual asset validation and unit conversion are active. Press Run query."
        except Exception as exc:
            self.report_note.text = "Cannot apply report: " + html.escape(str(exc))

    def current_bundle(self):
        if self.bundle_configuration:
            config = json.loads(json.dumps(self.bundle_configuration))
            config["baseline"] = self.bundle_baseline.value
            config["selected_sources"] = list(dict.fromkeys([self.bundle_baseline.value, *self.source_choice.value]))
            selected_ids = set(self.bundle_sections.value)
            config["sections"] = [s for s in config["sections"] if s["preset"] in selected_ids]
            existing = {s["preset"] for s in config["sections"]}
            config["sections"].extend({"id":identifier,"preset":identifier,"views":["Absolute","Difference"]}
                for identifier in self.bundle_sections.value if identifier not in existing)
            return validate_bundle(config)[1]
        filters = {k:v for k,v in json.loads(self.extra.value).items() if k in REPORT_FILTERS}
        if self.phase.value in {"LT", "LTPlan"}:
            filters["phase"] = self.phase.value
        filters.update({k:v for k,v in {"date_from":self.date_from.value, "date_to":self.date_to.value, "timeslice":self.timeslice.value}.items() if v})
        selected = list(self.source_choice.value)
        if self.bundle_baseline.value not in selected:
            selected.insert(0, self.bundle_baseline.value)
        if not self.bundle_sections.value:
            raise ValueError("Choose at least one report")
        return make_bundle(self.sources, self.bundle_baseline.value, presets=self.bundle_sections.value,
            selected_sources=selected, query_filters=filters, colors=self.plot_overrides["colors"], series_order=self.plot_overrides["series_order"])

    def save_bundle(self):
        try:
            self.bundle_text.value = json.dumps(self.current_bundle(), indent=2)
            self.bundle_status.text = "Report configuration ready to download. Keep source paths and IDs private."
        except Exception as exc:
            self.bundle_status.text = "Cannot save report configuration: " + html.escape(str(exc))

    def load_bundle(self):
        if self.job:
            self.bundle_status.text = "Wait for the current job before loading a report configuration."
            return
        try:
            self.apply_bundle(json.loads(self.bundle_text.value))
        except Exception as exc:
            self.bundle_status.text = "Cannot load report configuration: " + html.escape(str(exc))

    def _bundle_uploaded(self, attr, old, new):
        if new:
            try:
                self.bundle_text.value = base64.b64decode(new).decode("utf-8-sig")
                self.load_bundle()
            except Exception as exc:
                self.bundle_status.text = "Cannot read report configuration: " + html.escape(str(exc))

    def apply_bundle(self, config):
        sources, config = validate_bundle(config)
        self.bundle_loading = self.loading_config = True
        try:
            self.sources = sources
            labels = [s.label for s in sources]
            self.source_choice.options = labels
            self.source_choice.value = config["selected_sources"]
            self.baseline.options = self.bundle_baseline.options = labels
            self.baseline.value = self.bundle_baseline.value = config["baseline"]
            self.bundle_scenarios.options = labels
            self.bundle_scenarios.value = []
            self.bundle_sections.value = list(dict.fromkeys(s["preset"] for s in config["sections"]))
            self.bundle_configuration = config
            self.plot_overrides.update(colors=config.get("colors", {}), series_order=config.get("series_order", []), scale=1.0, unit_label="")
            query = config.get("query_filters", {})
            self.extra.value = json.dumps({k:v for k,v in query.items() if k in {"sample", "model", "band_id"}})
            self.phase.value = query.get("phase", "LTPlan")
            self.date_from.value = query.get("date_from", "")
            self.date_to.value = query.get("date_to", "")
            self.timeslice.value = query.get("timeslice", "All Periods")
            self.bundle_result = None
            self.frame = pd.DataFrame(columns=COLUMNS)
            self.chart.children = [Div(text="Report bundle loaded. Choose a single report preset for the Pivot tab.")]
            self.active_report = None
            self.report_choice.value = "custom"
            self.bundle_chart.children = [Div(text="Report configuration loaded. Press Build report bundle.")]
            self.bundle_status.text = "Report configuration loaded; no queries ran automatically."
        finally:
            self.bundle_loading = self.loading_config = False

    def run_bundle(self):
        if self.job:
            return
        try:
            config = self.current_bundle()
        except Exception as exc:
            self.bundle_status.text = "Cannot build reports: " + html.escape(str(exc))
            return
        self.bundle_result = None
        self.bundle_chart.children = [Div(text="Building annual reports…")]
        self.bundle_status.text = "Querying selected annual report sections…"
        self.tabs.active = 4
        refresh = 0 not in self.cache_options.active
        max_rows = int(self.bundle_max_rows.value)
        def work(cancel, emit):
            result = build_bundle(config, self.cache_dir, max_rows=max_rows, cancel=cancel,
                progress=lambda message:emit("bundle_progress",message), refresh=refresh)
            emit("bundle_result", result)
        self.start_job(work, kind="bundle")

    def _bundle_view_changed(self, attr, old, new):
        if self.bundle_result and not self.bundle_loading:
            result = next((r for r in self.bundle_result["sections"] if r["section"]["id"] == self.bundle_section.value), None)
            if result:
                try:
                    self.bundle_chart.children = [section_layout(result, scenarios=self.bundle_scenarios.value)]
                except Exception as exc:
                    self.bundle_chart.children = [Div(text="Cannot draw this report: " + html.escape(str(exc)))]

    def _preset_changed(self, attr, old, new):
        if new not in PRESETS or self.loading_config:
            return
        self.loading_config = True
        try:
            for name, value in PRESETS[new].items():
                if name != "net_total":
                    getattr(self, name).value = value
            self.display_options.active = ([0] if PRESETS[new]["net_total"] else []) + ([1] if 1 in self.display_options.active else [])
        finally:
            self.loading_config = False
        self.render()

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
        if not isinstance(extra, dict) or set(extra) - {"sample", "model", "category", "parent", "filter", "band_id"}:
            raise ValueError("Extra filters support only sample, model, category, parent, filter, band_id")
        query.update(extra)
        query = {k: v for k, v in query.items() if v not in (None, "", [])}
        return Selection(query, max_rows=int(self.max_rows.value), window_days=int(self.window_days.value))

    def start_job(self, work, kind="query"):
        if self.job is not None:
            return
        cancel, events = threading.Event(), queue.Queue(maxsize=4)
        self.job = (cancel, events)
        self.job_kind = kind
        self.run_button.disabled = self.explore_button.disabled = True
        self.build_bundle_button.disabled = self.apply_report_button.disabled = True
        self.analytics.busy(True)
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
        self.complete = False
        self.query_count = 0
        self.metadata.text = ""
        self.chart.children = [Div(text="Waiting for query results…")]
        self.table_source.data = {"x": [], "series": [], "unit": [], "value": []}
        self.pivot_note.text = ""
        self.status.text = "Querying selected solutions…"
        self.tabs.active = 1

        refresh = 0 not in self.cache_options.active

        def work(cancel, emit):
            for batch in query_cached(sources, selection, self.cache_dir, cancel,
                lambda source, origin: emit("progress", (source.label, origin)), refresh=refresh):
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

        self.start_job(work, kind="explore")

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
            if kind == "analysis_progress":
                self.analytics.message(value)
            elif kind == "analysis_result":
                self.analytics.ready(value)
            elif kind == "bundle_progress":
                self.bundle_status.text = html.escape(value)
            elif kind == "bundle_result":
                self.bundle_result = value
                self.bundle_loading = True
                self.bundle_section.options = [(r["section"]["id"], r["section"]["title"]) for r in value["sections"]]
                self.bundle_section.value = value["sections"][0]["section"]["id"]
                self.bundle_loading = False
                complete = sum(r["status"] == "complete" for r in value["sections"])
                self.bundle_status.text = f"Report bundle ready. {complete}/{len(value['sections'])} sections fully available; {value['query_rows']:,} queried rows. Shared baseline: {html.escape(value['config']['baseline'])}."
                self._bundle_view_changed(None, None, None)
            elif kind == "batch":
                self.frame = value.frame.copy() if self.frame.empty else pd.concat([self.frame, value.frame], ignore_index=True)
                self.query_count += len(value.frame)
                self.status.text = f"Received {self.query_count:,} rows; latest scenario: {html.escape(value.source.label)}. Results are provisional."
                changed = True
            elif kind == "progress":
                label, origin = value
                self.status.text = f"{'Reading cached results' if origin == 'cache' else 'Querying'}: {html.escape(label)}…"
            elif kind == "metadata":
                self.metadata.text = "<pre>" + html.escape(json.dumps(value, indent=2, default=str)) + "</pre>"
                self.tabs.active = 2
            else:
                if kind == "done":
                    if self.job_kind == "query":
                        self.complete = True
                        if self.active_report and not self.frame.empty:
                            try:
                                self.frame = prepare_annual(self.frame, self.active_report)
                            except ValueError as exc:
                                self.complete = False
                                self.frame = pd.DataFrame(columns=COLUMNS)
                                self.chart.children = [Div(text="Annual report validation failed: " + html.escape(str(exc)))]
                                self.status.text = "Annual report validation failed: " + html.escape(str(exc))
                    changed = self.job_kind == "query"
                    if self.job_kind == "query" and self.complete:
                        self.status.text = f"Complete. {self.query_count:,} result rows."
                    elif self.job_kind == "explore":
                        self.status.text = "Reported choices loaded."
                    elif self.job_kind == "analysis":
                        self.status.text = "Analysis finished; inspect coverage in Analytics."
                    elif self.job_kind == "bundle":
                        self.status.text = "Annual report bundle finished; inspect section coverage in Reports."
                else:
                    if self.job_kind == "query":
                        self.complete = False
                    self.status.text = "Stopped: " + html.escape(str(value)) + ". Query results may be incomplete."
                if kind != "done" and self.job_kind == "bundle":
                    self.bundle_status.text = self.status.text
                if kind != "done" and self.job_kind == "analysis":
                    self.analytics.message(self.status.text)
                self.job = None
                self.analytics.busy(False)
                self.run_button.disabled = self.explore_button.disabled = False
                self.build_bundle_button.disabled = self.apply_report_button.disabled = False
                self.cancel_button.disabled = True
                break
        if changed:
            for name, widget in self.filters.items():
                widget.options = sorted((set(self.frame[name]) | set(widget.value)) - {""})
            self.render()

    def _pivot_changed(self, attr, old, new):
        if not self.loading_config:
            self.render()

    def render(self):
        if self.frame.empty:
            return
        if (self.comparison.value != "Absolute" or self.active_report) and not self.complete:
            self.chart.children = [Div(text="Comparisons wait for a complete query; partial results cannot establish a baseline.")]
            return
        try:
            plot = self.plot_config()
            if self.active_report:
                plot = preset_plot(self.active_report, self.baseline.value, [s.label for s in self.sources], plot)
            filters = {k: v for k, v in plot["filters"].items() if k != "scenario"}
            table = pivot(self.frame, x=plot["x"], series=plot["series"], operation=plot["operation"],
                          filters=filters, facet=plot["facet"])
            table = compare(table, plot["baseline"], plot["comparison"], visible=plot["filters"].get("scenario"))
            if table.empty:
                self.chart.children = [Div(text="No measurements match these filters.")]
                self.table_source.data = {key: [] for key in self.table_source.data}
                self.pivot_note.text = "Clear or change the pivot filters."
                return
            charts, notes = build_charts(table, plot)
            self.chart.children = [charts]
            preview = table.head(1000)
            self.table_source.data = {"x": preview[plot["x"]].astype(str).tolist(),
                "series": preview[plot["series"]].astype(str).tolist(), "unit": preview.unit.tolist(),
                **{c: preview[c].tolist() for c in ("value", "absolute_value", "baseline_value", "comparison_status", "model_name")}}
            unmatched = int((~table.comparison_status.isin(["matched", "absolute"])).sum())
            self.pivot_note.text = (f"{len(table):,} pivot rows; table previews first 1,000. "
                f"{unmatched:,} missing or undefined comparisons. " + html.escape(" ".join(notes)) +
                " Values retain property, unit, phase, period, time slice, sample and band identity. "
                "Time axes aggregate using the chosen operation; source model names remain in the table and hover.")
        except Exception as exc:
            self.chart.children = [Div(text="Cannot draw this view: " + html.escape(str(exc)))]
            self.pivot_note.text = "Adjust comparison, chart, facets, or filters."


def make_document(doc, sources, *, workspace=None, cache_dir=None, bundle=None, analysis=None):
    return PivotApp(doc, sources, workspace=workspace, cache_dir=cache_dir, bundle=bundle, analysis=analysis)
