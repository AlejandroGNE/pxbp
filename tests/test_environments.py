"""Checks for interpreter selection and report process argument handling."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_rejects_conda_and_other_python_versions(tmp_path):
    setup = load_module("setup_environment", ROOT / "scripts/setup_environment.py")
    setup.check_interpreter((3, 12, 10), tmp_path)
    with pytest.raises(RuntimeError, match="3.12"):
        setup.check_interpreter((3, 11, 9), tmp_path)
    (tmp_path / "conda-meta").mkdir()
    with pytest.raises(RuntimeError, match="Conda"):
        setup.check_interpreter((3, 12, 10), tmp_path)


def test_report_uses_current_interpreter_without_path_or_shell(tmp_path, monkeypatch):
    runner = load_module("report_runner", ROOT / "X2BokehPivot/report_runner.py")
    script = tmp_path / "reports" / "probe.py"
    script.parent.mkdir()
    script.write_text("import json,sys; print(json.dumps([sys.executable,sys.argv[1:]]))", encoding="utf-8")
    output = tmp_path / "output with spaces" / "report"
    arguments = ["scenario with spaces", "literal & argument", "", str(output)]
    monkeypatch.setenv("PATH", str(tmp_path / "no-python-on-path"))
    process = runner.launch_report(script, arguments, output_dir=output)
    assert process.wait(timeout=30) == 0
    executable, actual = json.loads((output.parent / "report-process.log").read_text())
    assert Path(executable) == Path(sys.executable)
    assert actual == arguments
    # The report itself owns creating/archiving this directory.
    assert not output.exists()
