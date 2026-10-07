"""Set up independent pip/venv environments using standard CPython 3.12."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = {
    "native": (ROOT / ".venv-native", ROOT / "requirements-native.txt"),
    "viewer": (ROOT / "X2BokehPivot" / ".venv", ROOT / "X2BokehPivot" / "requirements.txt"),
    "modern": (ROOT / ".venv", None),
}


def check_interpreter(version, base_prefix):
    if tuple(version[:2]) != (3, 12):
        raise RuntimeError("These setup scripts require standard CPython 3.12. Install it from python.org or set PXBP_PYTHON to its executable.")
    if (Path(base_prefix) / "conda-meta").is_dir():
        raise RuntimeError("This interpreter is based on Conda. Use standard CPython 3.12 (py -3.12) or set PXBP_PYTHON to its executable.")


def python_path(directory):
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def verify(component, executable):
    probes = {
        "native": "import clr, pandas, dateutil; print('Native dependencies OK')",
        "viewer": "import sys; sys.path.insert(0, sys.argv[1]); import core, bokeh, pandas, numpy; print('ReEDS imports OK:', bokeh.__version__, pandas.__version__, numpy.__version__)",
        "modern": "import pxbp, bokeh; print('pxbp OK:', pxbp.__version__, 'Bokeh', bokeh.__version__)",
    }
    subprocess.run([str(executable), "-c", probes[component], str(ROOT / "X2BokehPivot")], check=True)


def setup(component, *, check_only=False):
    directory, requirements = ENVIRONMENTS[component]
    executable = python_path(directory)
    if not executable.is_file():
        if check_only:
            raise FileNotFoundError(f"Environment missing: {directory}. Run setup.bat {component} first.")
        print(f"Creating {directory} from {sys.executable}", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(directory)], check=True)
    probe = subprocess.run([str(executable), "-c", "import sys,json; print(json.dumps({'version':list(sys.version_info[:2]),'base_prefix':sys.base_prefix}))"],
                           check=True, capture_output=True, text=True)
    interpreter = json.loads(probe.stdout)
    check_interpreter(interpreter["version"], interpreter["base_prefix"])
    if not check_only:
        if requirements is None:
            command = [str(executable), "-m", "pip", "install", "-e", str(ROOT) + "[test]"]
        else:
            command = [str(executable), "-m", "pip", "install", "-r", str(requirements)]
        subprocess.run(command, check=True, cwd=str(ROOT))
    verify(component, executable)
    print(f"Ready: {component} uses {executable}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", nargs="?", choices=[*ENVIRONMENTS, "all"], default="native")
    parser.add_argument("--check", action="store_true", help="Check existing environments without installing")
    args = parser.parse_args(argv)
    try:
        check_interpreter(sys.version_info, sys.base_prefix)
        for component in ENVIRONMENTS if args.component == "all" else [args.component]:
            setup(component, check_only=args.check)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
