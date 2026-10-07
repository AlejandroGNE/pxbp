"""Launch the classic app with this environment's interpreter and absolute paths."""
import argparse
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true")
    args, bokeh_args = parser.parse_known_args(argv)
    root = Path(__file__).resolve().parent
    command = [sys.executable, "-m", "bokeh", "serve", str(root),
               "--address", "127.0.0.1", "--port", "0"]
    if not args.no_browser:
        command.append("--show")
    try:
        return subprocess.call(command + bokeh_args, cwd=str(root))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
