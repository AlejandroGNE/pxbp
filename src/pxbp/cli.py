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
        workspace = None
        if args.command == "serve" and args.workspace:
            if args.config or args.solution_id or args.parquet:
                raise ValueError("Use serve --workspace or source options, not both")
            from .workspace import read_workspace
            sources, workspace = read_workspace(args.workspace)
        if args.config and (args.solution_id or args.parquet):
            raise ValueError("Use --config or direct source options, not both")
        if workspace is None:
            sources = load_sources(args.config) if args.config else [Source(f"Solution {i}", value)
                       for i, value in enumerate(args.solution_id, 1)]
        if not args.config and workspace is None:
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
            server = Server({"/": Application(FunctionHandler(lambda doc: make_document(doc, sources, workspace=workspace, cache_dir=args.cache_dir)))},
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
