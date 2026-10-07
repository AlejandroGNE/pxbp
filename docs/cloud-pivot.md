# On-demand Cloud pivot (0.2)

The `pxbp` application is independent of the original `X2BokehPivot` scripts.
It queries a set of solution IDs when you press **Run query**, then pivots the
returned rows directly. No mappings, file renaming, or pre-exported scenario
CSV directory is required. Existing ZIP/CSV tooling remains available.

## Install

Use a fresh Python 3.10+ environment from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
```

Git must be on PATH to install the pinned `plexos-query` dependency. For local
development using a checkout of the reference repository:

```powershell
.\.venv\Scripts\python.exe -m pip install -e 'C:\path\to\plexos-query'
.\.venv\Scripts\python.exe -m pip install 'bokeh>=3.4,<4' 'pandas>=2.2,<3' pytest
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

The Cloud adapter builds on [plexos-query cloud guidance](https://github.com/AlejandroGNE/plexos-query/blob/main/docs/cloud-query.md).
The dependency is pinned because the later local adapter also needs its SQL
builder. Do not upgrade that dependency without running adapter tests.

Install and authenticate PLEXOS Cloud CLI separately. Confirm
`plexos-cloud solution sql --help` works, and use your organization's normal
CLI login/environment setup. `pxbp` uses the CLI's existing authentication;
it never asks for or stores credentials. `plexos-cloud auth --help` lists
authentication commands supported by your installed CLI.

## Select solutions and launch

Copy `examples/cloud-sources.json` to `sources.private.json`, replace the
placeholder UUIDs, and give each solution a unique scenario label. Those
placeholder IDs are valid JSON examples, not working Cloud resources.

```powershell
.\.venv\Scripts\pxbp.exe --config sources.private.json serve
# Or repeat IDs directly (labels become Solution 1, Solution 2, ...):
.\.venv\Scripts\pxbp.exe --solution-id <UUID1> --solution-id <UUID2> serve
```

The server binds to `127.0.0.1:5006`, opens a browser, and remains running in
the terminal. Use `--port 5007` if occupied, or `--port 0` for an available
port. `--no-browser` suppresses opening the browser. Stop with Ctrl+C.
Global source options go **before** `serve`, `query`, or `explore`.

1. Select the solutions to compare. Press **Explore collection** to inspect
   reported phases, periods, properties, time slices, samples, models, bands,
   categories and object names in the first selected solution. Exploration
   is evidence for that solution only; others may report different choices.
2. Set collection/property names. The default is Generator Generation,
   STSchedule, Interval, All Periods, category SUM; it is not guaranteed to
   exist in every solution. Blank optional choices mean all. Specify sample
   and model filters when you need a particular reported series.
3. Put exact object names on separate lines. A comma inside an object name
   is preserved. Multiple properties use comma-separated names/IDs.
4. Dates filter period **start timestamps**, inclusive at both ends.
   `2024-01-31` means midnight, not the entire last day. Use an explicit time
   such as `2024-01-31T23:59:59` when needed. Times follow solution timestamps;
   the app does not infer your solution's time zone.
5. Run. Change pivot X, series, operation and filters without another Cloud
   request. Run again after changing query choices to fetch a new result.
   Year/month/day/hour axes combine repeated dates; use `start_date` to keep
   complete chronology. Legend clicks hide/show individual series.

Properties, units, phases, period types, time slices, samples, models and
bands remain separate pivot groups. Scenario identity is retained even if
you choose another legend dimension. The chart displays at most 100 series
and the table previews 1,000 pivot rows, with counts displayed explicitly.
Line charts include points so one-period results are visible. Bars for
different scenarios overlap; use lines or hide legend series to compare.

## What streams

The installed CLI exports each SQL result to a temporary CSV, then the app
reads it in bounded batches and progressively updates the in-memory pivot.
It does not require saved CSV exports. **The remote SQL request itself is
not a proven row-by-row streaming API.** A single query must finish before
its first batch can be displayed. Each solution is queried sequentially.

For earlier progress on a long horizon, set both date bounds and set
**Cloud window days** (e.g. 7). Each request covers a disjoint half-open
window and the original inclusive bounds still apply. Category/object/raw
queries work this way. Period aggregation cannot be split into windows:
averages and other aggregates cannot safely be recombined from chunks.

Maximum rows defaults to 100,000 **across all solutions**. SQL requests use
the remaining budget plus one row to detect overflow. Overflow, errors and
cancellation mark the displayed results incomplete; narrow the query and
rerun before treating the totals as final. The server retains the selected
rows in memory, so this is a bounded interactive viewer, not a limitless
data warehouse. Workers use a bounded queue to apply backpressure.

Cancel stops the active CLI process and further windows. Closing the session
also signals cancellation. Each CLI call has a 180-second default timeout.
Authentication, authorization, empty reporting selections, and Cloud data
preparation errors are shown without hiding already received results.
Cloud resource status `Complete` alone does not guarantee SQL readiness.

## Command line and verification

```powershell
.\.venv\Scripts\pxbp.exe --config sources.private.json explore --collection SystemGenerators
.\.venv\Scripts\pxbp.exe --config sources.private.json query --selection examples/generation-query.json
.\.venv\Scripts\python.exe -m pytest -q
```

`query` writes one JSON array per batch on stdout and flushes it immediately.
Diagnostics go to stderr; nonzero exit means the stream is incomplete.
Query choices are a JSON object matching the example. Query-only flags
include `--max-rows`, `--batch-size`, `--timeout`, and `--window-days`.

The Bokeh UI updates models only in document callbacks while queries run
in a background thread, following the [Bokeh server threading guidance](https://docs.bokeh.org/en/3.10.0/docs/user_guide/server/app.html).
See the workflow audit for live checks and service limitations discovered.
