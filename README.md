# PLEXOS2BokehPivot (`pxbp`)

The original Windows workflow queries PLEXOS **solution ZIPs** with the native
PLEXOS API, writes category totals to CSV, and opens the bundled Bokeh Pivot.
An input model XML by itself is not a solved result.

## On-demand cloud queries

The next version adds a separate current Bokeh application. Give it Cloud
solution IDs, run selected queries, and compare/pivot results as batches
arrive. Start with [the cloud pivot guide](docs/cloud-pivot.md).

## Original ZIP → CSV → Pivot workflow

Run commands from this repository root. Windows, an installed PLEXOS API,
and its runtime/licensing prerequisites are required for the original scripts.
Both `Plexos2BokehPivot.py` and `mappings.py` use the hardcoded API directory
`C:/Program Files/Energy Exemplar/PLEXOS 10.0 API`; change it in both files
if your installation differs. A Python environment alone does not install PLEXOS.

1. Run `setup.bat`. It installs Miniforge under `%LOCALAPPDATA%/Miniforge3`
   and creates `xml2csv` from `environment.yaml`. If the environment already
   exists, use `conda env update -n xml2csv -f environment.yaml` instead of
   recreating it. Check actual errors: the batch file can print success after
   a failed environment creation.
2. Create `PlexosSolutions` if missing. Put solved `.zip` files **directly in
   that folder**, one ZIP per scenario. The script does not recurse into
   scenario subfolders. Keep each ZIP intact, including its `*Solution.xml`.
3. Edit `mappings.json`: collection enum IDs are keys and property enum IDs
   are integer lists. Only reported properties can return results. IDs are
   collection-specific; verify them with your PLEXOS version/report settings.
   There is no `config.csv` or `configuration.json` in this workflow.
4. Optionally regenerate that mapping with `map.bat` (not `setting.bat`).
   Before running it, edit the model XML path in `get_report_properties()`
   and `model_name` in `main()` in `mappings.py`. These are example-specific
   hardcoded choices. The interactive script selects collections/properties
   and overwrites `mappings.json`; it does not map arbitrary CSV columns.
5. Set the phase in `process_collection_chunk()` and the period in `main()`
   of `Plexos2BokehPivot.py`. The committed legacy script originally selects
   `LTPlan` and prompts for `FiscalYear` or `Interval`. Some working copies
   select `STSchedule` and hardcode `FiscalYear`; inspect your actual script.
   It uses category aggregation with SUM and outputs
   `category_name,p1,year,month,day,hour,value`.
6. Run `.\launch.bat` from the root. It runs extraction, `postrename.py`,
   then `postappend.py`. Output layout is
   `runs/<period>/<ZIP filename without .zip>/outputs/*.csv`.
   Extraction replaces the corresponding property files. Renaming also
   replaces matching destination files, so back up results you need first.
7. Check the console and `error_log.txt` for failures before visualizing.
   A process finishing does not guarantee every property succeeded.

The rename table in `postrename.py` must match your chosen collection/property
IDs and Bokeh result definitions in `X2BokehPivot/reeds2.py`. For example,
Generator property 2 becomes `gen_ann.csv`. A property not in the rename table
stays `collection_<id>_property_<id>.csv` and is not automatically registered
as a ReEDS result. `_apend` is the spelling used by the rename/append scripts;
the extractor's separate `_append` helper is a different convention.
`postrename.py` walks the current directory, so always launch from this root.

## Open the original viewer

```powershell
cd X2BokehPivot
.\setup.bat
.\launch.bat
```

This is a separate `bokehpivot` environment with older pinned versions in
`X2BokehPivot/environment.yaml`. Run its launcher from **inside that folder**:
it serves `.`. Its server picks a free port and opens a browser. Keep the
terminal running; stop the server with Ctrl+C.

Select the appropriate data type and paste an absolute path to
`runs/<period>` so its immediate scenario folders contain `outputs`. If the
prefilled path does not load, change it and press Enter, then restore it and
press Enter to trigger the path callback. For an unregistered property file,
use the CSV data type and point directly to that CSV; do not mix incompatible
CSV schemas in a directory. Technology colors live in
`X2BokehPivot/in/reeds2/tech_style.csv`.

The ReEDS 2 viewer discovers a scenario only if `outputs/cap.csv` exists.
If your configured capacity property is not renamed to `cap.csv`, the
scenario is invisible in that mode. For example, the current working copy
selects Generator property 212 while the rename table expects 214: reconcile
these using your API's actual property enums before relying on this mode.

The legacy hourly chart uses hour-of-day, not a complete timestamp. Select
one year/month/day for hourly data, one year/month for daily data, and one
 year for monthly data, or split the chart by those dimensions to avoid
combining different dates.

See [the workflow audit](docs/workflow-audit.md) for discovered gaps and checks.
