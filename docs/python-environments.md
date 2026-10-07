# Standard Python environments (no Conda)

The Windows setup, extraction, mapping and viewer launchers use standard
CPython 3.12 with the built-in `venv` module and pip. They do not install or
activate Miniforge/Conda, modify security controls, or change your existing
Conda environments. The old environment YAML files were replaced by pip
requirements and the modern package's `pyproject.toml`.

## Prerequisites and setup

Install standard 64-bit Python 3.12 from [python.org](https://www.python.org/downloads/windows/).
The provided setup scripts target 3.12 so the tested binary wheels and
classic viewer dependency versions are consistent. Verify `py -3.12 --version`.
Git on PATH is also needed when installing modern `pxbp`'s pinned reference
repository dependency. Native ZIP extraction still needs your PLEXOS API
installation and its .NET/runtime/licensing prerequisites; pip does not
install those. Querying already-converted local Parquet does not need them.

From the repository root:

```powershell
.\setup.bat all
# Or install one component:
.\setup.bat native
.\setup.bat viewer
.\setup.bat modern
```

| Component | Environment | Dependencies | Launcher |
| --- | --- | --- | --- |
| Native ZIP extraction/mapping | `.venv-native` | `requirements-native.txt` | `launch.bat`, `map.bat` |
| Classic ReEDS/Bokeh viewer | `X2BokehPivot/.venv` | `X2BokehPivot/requirements.txt` | `X2BokehPivot/launch.bat` |
| Modern Cloud/Parquet viewer | `.venv` | `pyproject.toml` | `pxbp.bat` |

Separate environments are intentional: the classic viewer uses Bokeh 2.4.3
and NumPy 1.26.4; modern `pxbp` uses Bokeh 3. Mixing those versions in one
environment would change the classic widget/glyph interfaces.

Setup defaults to `py -3.12`. If the Windows launcher is absent, it tries
`python` on PATH and validates that it is standard Python 3.12. To choose a
specific interpreter in PowerShell:

```powershell
$env:PXBP_PYTHON = 'C:\path\to\Python312\python.exe'
.\setup.bat all
```

Do not set that variable to a Conda interpreter. Setup explicitly rejects a
Conda base and also checks existing venvs before updating them. If an old
environment was created from the wrong Python, preserve any work you need,
move that environment aside and rerun setup. Setup does not delete it.

Run setup again to install the declared dependencies. For a read-only import
check of existing environments:

```powershell
.\setup.bat all --check
```

## Launch

```powershell
.\launch.bat                         # Native extraction/rename/append
.\map.bat                            # Interactive native mapping
.\X2BokehPivot\launch.bat             # Classic ReEDS viewer
.\pxbp.bat --parquet 'C:\models\solution-parquet' serve
.\pxbp.bat --solution-id <UUID> serve
```

No activation is needed: launchers call their exact environment interpreter.
They resolve the repository/viewer directories even when invoked from
another working directory. Classic viewer Bokeh options are forwarded:

```powershell
.\X2BokehPivot\launch.bat --no-browser --port 5018
```

The classic URL is `http://localhost:5018/X2BokehPivot` for that command.
Use `localhost` to match Bokeh's WebSocket origin. If the browser was open
during a server restart, refresh it to get a fresh session.

Both classic report builders now launch `sys.executable` with a list of
arguments, rather than `start python` and a shell command. This keeps reports
in the viewer environment and preserves spaces/special characters in paths.
Normal report workers run without an extra console window. Their output is
logged beside the report directory as `<report-directory>-process.log`.
Selecting Debug Mode intentionally opens an interactive debugger console.

## Scope of the migration

This changes how the existing applications are installed and started. It
does not remap PLEXOS properties or certify every ReEDS result definition.
The classic scenario discovery still requires `outputs/cap.csv`. Its full
legacy feature set remains in place; modern `pxbp` remains a separate viewer.

The original standalone `ptvsd` import was removed: it was only used by
commented example debugger code, and is not needed to load results or reports.
The standard `venv` workflow follows [Python's documentation](https://docs.python.org/3.12/library/venv.html).
