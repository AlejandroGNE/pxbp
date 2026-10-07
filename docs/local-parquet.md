# Direct local Parquet pivot (0.3)

`pxbp` reads already-converted PLEXOS solution Parquet directly with DuckDB,
streams selected rows into memory, and uses the same Bokeh pivot as Cloud.
**No CSV is written or read in the local path.** Local queries do not need a
PLEXOS native API installation, Cloud login, or the Cloud CLI. The adapter
does not process a standalone arbitrary Parquet file as a solved solution.

Install with `.\setup.bat modern`, then use `.\pxbp.bat` for the commands
below. See [standard Python setup](python-environments.md) for prerequisites.

## Required solution layout

Give the app a directory containing all three PLEXOS tables:

```text
baseline/
  fullkeyinfo/**/*.parquet
  data/**/*.parquet
  period/**/*.parquet
  membershipinfo/**/*.parquet   (optional)
```

These are the metadata, values and periods created by PLEXOS Cloud CLI's
ZIP-to-Parquet conversion. Keep the converted directory intact. If you
still have only a native ZIP, conversion is a separate preparatory step:

```powershell
plexos-cloud solution convert zip-to-parquet --zipPath 'solution.zip' --outputDirectory 'solution-parquet'
```

That conversion command needs the CLI; querying existing Parquet does not.
The app reports missing tables/columns rather than guessing the schema.

## Launch and compare

Install as described in [the cloud guide](cloud-pivot.md), then:

```powershell
.\.venv\Scripts\pxbp.exe --parquet 'C:\models\baseline' --parquet 'C:\models\alternative' serve
.\.venv\Scripts\pxbp.exe --parquet 'C:\models\baseline' explore --collection SystemGenerators
.\.venv\Scripts\pxbp.exe --parquet 'C:\models\baseline' query --selection examples/generation-query.json
```

Or copy `examples/local-sources.json` to a private configuration and edit
the paths/labels. **Relative paths resolve against the configuration file's
directory**, not the launcher's working directory. JSON Windows paths use
forward slashes or escaped backslashes.

```powershell
.\.venv\Scripts\pxbp.exe --config sources.private.json serve
```

A configuration can mix Cloud and local solutions:

```json
{
  "sources": [
    {"label": "Cloud baseline", "solution_id": "00000000-0000-0000-0000-000000000001"},
    {"label": "Local alternative", "path": "C:/models/alternative"}
  ]
}
```

Each source has exactly one `solution_id` or `path`, and a unique nonempty
label. Direct `--solution-id` and `--parquet` options can also be combined.
The exact same query is applied to every selected source; results retain
scenario label, source kind, Cloud ID/local path and reported series metadata.
Check reporting choices in each solution before comparing their results.

## Behavior and limits

* Query names, object filters, aggregation, row budgets, timestamps and pivot
  controls are shared with Cloud. Blank optional filters mean all.
* The local adapter uses the pinned `plexos-query` Values SQL builder.
  DuckDB reads Parquet with filter predicates and returns `fetchmany` batches.
  It never creates intermediate CSVs or calls `QueryToCSV`.
* Local connections are created and closed in the query worker. Cancel
  interrupts active DuckDB query execution; timeout defaults to 180 seconds.
  Exploration checks cancellation before opening a solution; its metadata
  call currently completes synchronously in the worker.
* Cloud window days are a remote latency/progress option. Local reads use
  one query, with the same original date predicates, even in mixed sessions.
* The viewer supports long-form Values and the common Cloud/local query
  choices. It does not expose the reference library's wider Names/Properties
  pivots, membership selectors, or List aggregation.
* Memory is bounded by the configured interactive row budget, not the size
  of the whole solution. DuckDB may still scan large inputs or spill for
  aggregation. Use dates/object/category filters to narrow large queries.

See [the workflow audit](workflow-audit.md) for automated and real-solution
validation. The local adapter intentionally depends on a private SQL builder
in a pinned reference revision; tests are required before changing that pin.
