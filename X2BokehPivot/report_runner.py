"""Start reports with the viewer's exact interpreter, without PATH activation."""
import subprocess
import sys
from pathlib import Path


def launch_report(script, arguments, *, output_dir, debug=False):
    script = Path(script).resolve()
    output = Path(output_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable]
    if debug:
        command += ["-m", "pdb"]
    command += [str(script), *[str(value) for value in arguments]]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_CONSOLE if debug else subprocess.CREATE_NO_WINDOW
    if debug:
        return subprocess.Popen(command, cwd=str(script.parent.parent), creationflags=flags)
    with (output.parent / (output.name + "-process.log")).open("w", encoding="utf-8") as log:
        return subprocess.Popen(command, cwd=str(script.parent.parent), stdout=log,
                                stderr=subprocess.STDOUT, creationflags=flags)
