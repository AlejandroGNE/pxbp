"""Exercise automatic browser launch against an actual ephemeral Bokeh server."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("no_browser", [False, True])
def test_browser_url_matches_server_origin(no_browser):
    code = r"""
import webbrowser
from tornado.ioloop import IOLoop
from pxbp.cli import main

opened = []
loop = IOLoop.current()
def open_browser(url):
    opened.append(url)
    loop.stop()
    return True
webbrowser.open = open_browser
loop.call_later(1, loop.stop)
args = ["--solution-id", "00000000-0000-0000-0000-000000000001", "serve", "--port", "0"]
if NO_BROWSER:
    args.append("--no-browser")
assert main(args) == 0
if NO_BROWSER:
    assert not opened
else:
    assert len(opened) == 1
    assert opened[0].startswith("http://localhost:")
    assert not opened[0].endswith(":0/")
    print("OPENED " + opened[0])
""".replace("NO_BROWSER", repr(no_browser))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, timeout=30, check=True)
    printed = next(line.split(": ", 1)[1] for line in result.stdout.splitlines()
                   if line.startswith("PLEXOS Bokeh Pivot: "))
    if not no_browser:
        assert "OPENED " + printed in result.stdout
