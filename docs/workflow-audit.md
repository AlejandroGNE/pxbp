# Workflow audit — 2026-10-06

The audit follows the scripts and README and preserves existing uncommitted edits.

## Gaps corrected

* `config.csv`, `setting.bat`, Mapping/Execute modes and `configuration.json`
  were documented but absent. Actual configuration is `mappings.json`/`map.bat`.
* Solutions must be intact ZIPs in a flat folder, not model XML or scenario subfolders.
* Phase and period require script edits/input; HEAD and the working copy differ.
* Mapping generation requires a model XML path and exact model name.
* Output is `runs/<period>/<scenario>/outputs`, which determines the viewer path.
* Fixed postprocessing names do not cover all configured properties.
* Root and viewer environments and working directories are separate.
* Root setup can print success even after environment creation fails.

## Workstation checks

* Native PLEXOS `Solution` imported using existing `xml2csv` and PLEXOS 10.0 API.
* Three private, ignored local solution ZIPs were found (about 146–154 MB each).
* Existing `bokehpivot/python.exe` returned Windows Access Denied when invoked.
  Its presence does not establish that the pinned legacy environment is usable.
* Cloud CLI is installed. `solution sql --help` confirms SQL files,
  `--solution-id`, and CSV output support.

Further execution findings and new-version checks will be added as exercised.
Validation does not imply full native PLEXOS API parity.

## Additional discoveries

* ReEDS scenario discovery requires `outputs/cap.csv`, not merely a folder
  with result files. The working mapping selects property 212 while the
  capacity rename rule expects 214. This can hide an otherwise populated run.
* A read-only native Generator Generation/FiscalYear/category SUM query
  against the existing 2023 Copperplate Linear solution returned 20 rows.
* Recently completed Cloud Parquet resources returned an InternalServerError
  stating that solution data was being prepared. Resource completion and
  query readiness are separate; this is a service response, not a local
  installation failure.

## Cloud version validation

* Isolated legacy extraction → rename → append ran successfully against the
  2023 Copperplate Linear solution, producing 20 `gen_ann.csv` rows with the
  expected seven-column schema. Existing `runs` were not changed.
* A previously validated ERCOT Cloud solution returned seven daily Node
  Price rows for one exact node and All Periods. The new adapter delivered
  batches of 3, 3 and 1. One observed run took 11.72 seconds including metadata.
* Disjoint two-day Cloud windows returned exactly the same seven rows as
  the single request, including start/end boundary timestamps.
* Nine automated tests passed with Bokeh 3.10.0, pandas 2.3.3 and DuckDB 1.5.6:
  batch/provenance handling, global row-budget failures, cancellation,
  subprocess timeout/error cleanup, windows, config validation, pivot
  identity and Bokeh document construction/rendering/worker completion.
* Only selected Cloud CSV results are downloaded temporarily. This does not
  establish that the service or CLI streams rows before completing a request.
* Browser testing caught a blank page from a hostname mismatch: the initial
  launcher printed `127.0.0.1` while Bokeh allowed `localhost`. The launcher
  now prints the matching `localhost` URL, including when choosing port 0.

## Local version validation

* Fourteen tests passed, including actual DuckDB queries on generated PLEXOS
  table fixtures, exact object names containing commas, aggregation, missing
  schema, relative config paths and the JSON streaming CLI.
* Local tests replace `QueryToCSV` and the Cloud subprocess runner with
  failures: the local query still succeeds and creates no CSV files.
* The real converted ERCOT solution returned the same seven Node Price rows
  as Cloud, matching dates, values and all common normalized metadata. One
  observed local run took 0.22 seconds; this is not a general benchmark.
* A mixed session returned 14 rows: seven Cloud and seven local, with correct
  scenario labels and source provenance.
* The Cloud browser session completed the real seven-row query and rendered
  the pivot, confirming live WebSocket and document updates.
