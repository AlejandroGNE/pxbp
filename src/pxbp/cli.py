"""Launch the viewer, inspect a collection, or stream query batches as JSON lines."""
from __future__ import annotations

import argparse
import json
import sys
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
    explore = sub.add_parser("explore")
    explore.add_argument("--collection", required=True)
    query = sub.add_parser("query")
    query.add_argument("--selection", required=True, help="JSON query object file")
    query.add_argument("--max-rows", type=int, default=100000)
    query.add_argument("--batch-size", type=int, default=5000)
    query.add_argument("--window-days", type=int, default=0)
    query.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    try:
        if args.config and (args.solution_id or args.parquet):
            raise ValueError("Use --config or direct source options, not both")
        sources = load_sources(args.config) if args.config else [Source(f"Solution {i}", value)
                   for i, value in enumerate(args.solution_id, 1)]
        if not args.config:
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
            server = Server({"/": Application(FunctionHandler(lambda doc: make_document(doc, sources)))},
                            address="127.0.0.1", port=args.port)
            server.start()
            print(f"PLEXOS Bokeh Pivot: http://localhost:{server.port}/", flush=True)
            if not args.no_browser:
                server.io_loop.add_callback(server.show, "/")
            server.io_loop.start()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"pxbp: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
