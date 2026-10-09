"""Launch the viewer, inspect a collection, or stream query batches as JSON lines."""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
import zipfile
from pathlib import Path

from .sources import Selection, Source, load_sources, reader_for, stream_query


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="JSON source configuration")
    parser.add_argument("--solution-id", action="append", default=[], help="Cloud solution UUID; repeat for comparisons")
    parser.add_argument("--parquet", action="append", default=[], help="Converted local solution folder; repeat for comparisons")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=5006)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--analysis", help="Saved analytical report workspace")
    serve.add_argument("--bundle", help="Annual report bundle configuration")
    serve.add_argument("--workspace", help="Saved comparison workspace; supplies sources and view settings")
    serve.add_argument("--cache-dir", help="Optional private Parquet query cache")
    discover = sub.add_parser("discover", help="Create a source list from converted solution folders")
    discover.add_argument("--root", required=True)
    discover.add_argument("--pattern", default="*")
    discover.add_argument("--output", required=True)
    snapshot = sub.add_parser("snapshot", help="Query a workspace and save an offline chart snapshot")
    snapshot.add_argument("--workspace", required=True)
    snapshot.add_argument("--output", required=True)
    snapshot.add_argument("--cache-dir")
    snapshot.add_argument("--max-rows", type=int, default=1000000)
    snapshot.add_argument("--timeout", type=float, default=600)
    sub.add_parser("analysis-presets", help="List analytical recipes")
    ac = sub.add_parser("analysis-config", help="Create analysis configuration from an annual bundle or workspace")
    origin = ac.add_mutually_exclusive_group(required=True)
    origin.add_argument("--bundle"); origin.add_argument("--workspace")
    ac.add_argument("--output", required=True)
    ac.add_argument("--from", dest="date_from", required=True)
    ac.add_argument("--to", dest="date_to", required=True)
    ac.add_argument("--presets", help="Comma-separated recipes or all")
    ae = sub.add_parser("analysis", help="Export offline analytical HTML, PDF, and audited Parquets")
    ae.add_argument("--spec", required=True); ae.add_argument("--output", required=True)
    ae.add_argument("--cache-dir"); ae.add_argument("--max-rows", type=int, default=2000000)
    ae.add_argument("--timeout", type=float, default=600)
    sub.add_parser("presets", help="List annual report presets")
    bundle_config = sub.add_parser("bundle-config", help="Create an annual bundle from an existing workspace")
    bundle_config.add_argument("--workspace", required=True)
    bundle_config.add_argument("--output", required=True)
    bundle_config.add_argument("--presets", help="Comma-separated preset IDs; default is the core annual library")
    bundle_command = sub.add_parser("bundle", help="Export an annual report bundle as offline HTML, PDF, and audited Parquet")
    bundle_command.add_argument("--spec", required=True)
    bundle_command.add_argument("--output", required=True)
    bundle_command.add_argument("--cache-dir")
    bundle_command.add_argument("--max-rows", type=int, default=1000000)
    bundle_command.add_argument("--timeout", type=float, default=600)
    explore = sub.add_parser("explore")
    explore.add_argument("--collection", required=True)
    query = sub.add_parser("query")
    query.add_argument("--selection", required=True, help="JSON query object file")
    query.add_argument("--max-rows", type=int, default=100000)
    query.add_argument("--batch-size", type=int, default=5000)
    query.add_argument("--window-days", type=int, default=0)
    query.add_argument("--timeout", type=float, default=180)
    report = sub.add_parser("report", help="Export audited annual reports as offline HTML and PDF")
    report.add_argument("--spec", required=True, help="JSON capacity or annual-metrics specification")
    report.add_argument("--output", required=True, help="New output folder")
    report.add_argument("--max-rows", type=int, default=1000000)
    report.add_argument("--timeout", type=float, default=600)
    annual = sub.add_parser("import-annual-zip", help="Import native annual build summaries into Parquet")
    annual.add_argument("--zip", required=True, help="Downloaded solution ZIP")
    annual.add_argument("--output", required=True, help="New Parquet output folder")
    native = sub.add_parser("import-native-annual", help="Select annual properties from a ZIP directly into Parquet")
    native.add_argument("--zip", required=True)
    native.add_argument("--output", required=True)
    native.add_argument("--spec", required=True, help="JSON years and collection/property arrays")
    native.add_argument("--api-path", required=True, help="Installed compatible PLEXOS API folder")
    args = parser.parse_args(argv)
    try:
        if args.command == "analysis-presets":
            from .analytics_catalog import RECIPES
            for name,r in RECIPES.items():print(f"{name:30} {r['resolution']:12} {r['title']}")
            return 0
        if args.command == "analysis-config":
            from .analytics import make_analysis
            from .analytics_catalog import RECIPES
            if args.bundle:
                from .bundles import read_bundle
                sources,old=read_bundle(args.bundle);baseline=old["baseline"];style=old
                filters={k:v for k,v in old["query_filters"].items() if k in {"phase","sample","model","band_id","timeslice"}}
            else:
                from .workspace import read_workspace
                sources,old=read_workspace(args.workspace);baseline=old["plot"]["baseline"] or sources[0].label;style=old["plot"]
                filters={k:v for k,v in old["query"].items() if k in {"phase","sample","model","band_id","timeslice"}}
            recipes=list(RECIPES) if args.presets=="all" else [k.strip() for k in args.presets.split(",") if k.strip()] if args.presets else None
            cfg=make_analysis(sources,baseline,selected_sources=old["selected_sources"],date_from=args.date_from,date_to=args.date_to,
                filters=filters,colors=style.get("colors",{}),series_order=style.get("series_order",[]),recipes=recipes)
            target=Path(args.output).resolve()
            if target.exists():raise ValueError("Analysis configuration output already exists")
            target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(cfg,indent=2),encoding="utf-8")
            print(f"Analysis configuration saved: {target}");return 0
        if args.command == "analysis":
            from .analytics import export_analysis
            print(f"Analysis saved: {export_analysis(args.spec,args.output,args.cache_dir,max_rows=args.max_rows,timeout=args.timeout,progress=lambda m:print(m,flush=True))}")
            return 0
        if args.command == "presets":
            from .report_library import PRESETS
            for identifier, preset in PRESETS.items():
                print(f"{identifier:24} {preset['title']} | {preset['collection']} / {preset['property']}")
            return 0
        if args.command == "bundle-config":
            from .workspace import read_workspace
            from .bundles import make_bundle
            from .report_library import COMMON_FILTERS
            sources, workspace = read_workspace(args.workspace)
            target = Path(args.output).expanduser().resolve()
            if target.exists():
                raise ValueError("Bundle configuration output already exists")
            presets = [value.strip() for value in args.presets.split(",") if value.strip()] if args.presets else None
            filters = {key:value for key,value in workspace["query"].items() if key in COMMON_FILTERS}
            config = make_bundle(sources, workspace["plot"]["baseline"] or sources[0].label,
                presets=presets, selected_sources=workspace["selected_sources"], query_filters=filters,
                colors=workspace["plot"]["colors"], series_order=workspace["plot"]["series_order"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(config, indent=2), encoding="utf-8")
            print(f"Bundle configuration saved: {target}")
            return 0
        if args.command == "bundle":
            from .bundles import export_bundle
            print(f"Report bundle saved: {export_bundle(args.spec, args.output, args.cache_dir, max_rows=args.max_rows, timeout=args.timeout, progress=lambda message: print(message, flush=True))}")
            return 0
        if args.command == "discover":
            from .discovery import discover_sources
            sources, metadata = discover_sources(args.root, args.pattern)
            target = Path(args.output).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError("Discovery output already exists; choose a new file")
            target.write_text(json.dumps({"sources": [{"label": s.label, "path": s.path} for s in sources]}, indent=2), encoding="utf-8")
            for item in metadata:
                print(f"{item['label']}: models={', '.join(item['models'])}")
            print(f"Sources saved: {target}")
            return 0
        if args.command == "snapshot":
            from .snapshot import export_snapshot
            print(f"Snapshot saved: {export_snapshot(args.workspace, args.output, args.cache_dir, args.max_rows, args.timeout)}")
            return 0
        if args.command == "import-native-annual":
            from .native_import import import_native_annual
            spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
            try:
                destination = import_native_annual(args.zip, args.output, spec, args.api_path)
            except Exception as exc:
                raise RuntimeError(f"Native annual import failed: {exc}") from exc
            print(f"Annual Parquet saved: {destination}")
            return 0
        if args.command == "import-annual-zip":
            from .annual_import import import_annual_zip
            print(f"Annual Parquet saved: {import_annual_zip(args.zip, args.output)}")
            return 0
        workspace, bundle, analysis = None, None, None
        if args.command == "serve" and args.analysis:
            if args.workspace or args.bundle or args.config or args.solution_id or args.parquet:
                raise ValueError("Use serve --analysis or other workspace/source options, not both")
            from .analytics import read_analysis
            sources,analysis=read_analysis(args.analysis)
        if args.command == "serve" and args.bundle:
            if args.workspace or args.config or args.solution_id or args.parquet:
                raise ValueError("Use serve --bundle or workspace/source options, not both")
            from .bundles import read_bundle
            sources, bundle = read_bundle(args.bundle)
        if args.command == "serve" and args.workspace:
            if args.config or args.solution_id or args.parquet:
                raise ValueError("Use serve --workspace or source options, not both")
            from .workspace import read_workspace
            sources, workspace = read_workspace(args.workspace)
        if args.config and (args.solution_id or args.parquet):
            raise ValueError("Use --config or direct source options, not both")
        if workspace is None and bundle is None and analysis is None:
            sources = load_sources(args.config) if args.config else [Source(f"Solution {i}", value)
                       for i, value in enumerate(args.solution_id, 1)]
        if not args.config and workspace is None and bundle is None and analysis is None:
            sources += [Source(f"Local {i}", path=str(Path(value).expanduser().resolve()))
                        for i, value in enumerate(args.parquet, 1)]
        if not sources:
            raise ValueError("Provide --config, --solution-id or --parquet")
        if args.command == "query":
            selection = Selection(json.loads(Path(args.selection).read_text(encoding="utf-8-sig")),
                                  batch_size=args.batch_size, max_rows=args.max_rows,
                                  window_days=args.window_days, timeout=args.timeout)
            for batch in stream_query(sources, selection):
                print(batch.frame.to_json(orient="records", date_format="iso"), flush=True)
        elif args.command == "report":
            from .reports import export_capacity, load_spec
            spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
            if "metrics" in spec:
                from .annual_metrics import export_metrics
                destination = export_metrics(sources, spec, args.output, max_rows=args.max_rows, timeout=args.timeout)
            else:
                destination = export_capacity(sources, load_spec(args.spec), args.output,
                                              max_rows=args.max_rows, timeout=args.timeout)
            print(f"Report saved: {destination}")
        elif args.command == "explore":
            import threading
            for source in sources:
                info = reader_for(source, threading.Event(), 180).explore(args.collection)
                print(json.dumps({"scenario": source.label, "reported": info}, default=str))
        else:
            from bokeh.application import Application
            from bokeh.application.handlers.function import FunctionHandler
            from bokeh.server.server import Server
            from .app import make_document
            server = Server({"/": Application(FunctionHandler(lambda doc: make_document(doc, sources, workspace=workspace, cache_dir=args.cache_dir, bundle=bundle, analysis=analysis)))},
                            address="127.0.0.1", port=args.port,
                            allow_websocket_origin=[f"localhost:{args.port}", f"127.0.0.1:{args.port}"] if args.port else None)
            server.start()
            print(f"PLEXOS Bokeh Pivot: http://localhost:{server.port}/", flush=True)
            if not args.no_browser:
                server.io_loop.add_callback(webbrowser.open, f"http://localhost:{server.port}/")
            server.io_loop.start()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"pxbp: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
