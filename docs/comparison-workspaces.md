# Comparison workspaces

A workspace saves the solution list, selected solutions, query, baseline,
filters, chart type, panel layout, colors, and display scale in one JSON file.
It works with Cloud and local Parquet sources. Loading it does not run queries.

## First try: 36 fictional solutions

Complete the main README's Windows installation first. Open PowerShell in the
PXBP folder and run these commands separately:

```powershell
.\.venv\Scripts\python.exe examples/create-pivot-demo.py
.\pxbp.bat serve --workspace work/pivot-demo/workspace.private.json --cache-dir work/pivot-demo/cache
```

The first command creates small fictional datasets and prints the saved
workspace path. If that folder already exists, choose a fresh location:
`--output work/pivot-demo-2`, and use that folder in the second command.

1. Keep PowerShell open. The second command opens the browser.
2. Press **Run query**. Wait for **Complete. 540 result rows.**
3. Open **Pivot**. The view contains one technology stack per scenario, with
   signed differences against **Baseline**. Black dots show net totals.
   In this example, decreasing gas exactly offsets increasing solar and wind,
   so net differences are zero.
4. Set **Show** to **Absolute** to see the original measurements.
5. Change **Baseline** to another case and set **Show** to **Difference**.
   This uses loaded data; it does not issue another query.
6. Try **Scenario areas** and **Technology comparisons** under **View preset**.
   Presets change plot settings and preserve your baseline/comparison mode.
7. To see percentage changes, choose **Technology comparisons**, then set
   **Show** to **Percent change**. Component percentages cannot be stacked.
8. Use **Filter scenario** to show a smaller selection. This hides the baseline
   plot when requested while keeping its measurements available for comparison.

## Save, reopen, or add solutions

1. Open **Workspace**.
2. Press **Prepare current configuration**, then **Download displayed
   configuration**. The browser downloads `workspace.private.json`.
3. Later, use the file chooser in **Workspace** to open that file, or launch:

   ```powershell
   .\pxbp.bat serve --workspace "C:\your-folder\workspace.private.json" --cache-dir work/query-cache
   ```

4. Press **Run query** after loading. The saved chart and query choices return.
5. To add solutions, edit the displayed configuration's `sources` array, give
   each source a unique label, add its label to `selected_sources`, then press
   **Apply displayed configuration** and **Run query**. A source has `label`
   and either `path` or `solution_id`, as in the main README's source examples.

Configuration exports contain source paths and solution IDs. Keep real
configurations and caches private. Browser uploads should use absolute source
paths; CLI loading resolves relative paths beside the configuration file.

## Discover a folder of local solutions

```powershell
.\pxbp.bat discover --root "C:\models\parquets" --pattern "policy-A_*" --output work/sources.private.json
.\pxbp.bat --config work/sources.private.json serve --cache-dir work/query-cache
```

Replace the root and wildcard with your own values. Discovery reads reported
model names from `fullkeyinfo` instead of assuming opaque folder names are
scenario names. Multiple reported models are listed in the terminal. Duplicate
model labels require selecting one run or assigning labels manually. Configure
the reported query choices, run, then choose the baseline and preset in Pivot.

## Plot configuration

| Setting | Choices or purpose |
|---|---|
| `chart_type` | `Line`, `Dot`, `Dot-Line`, `Bar` (grouped), `Stacked Bar`, `Stacked Area` |
| `comparison` | `Absolute`, `Difference`, `Percent change`, `Ratio` |
| `baseline` | An exact source label |
| `x`, `series`, `facet` | Pivot dimension names; `facet: "scenario"` makes one panel per scenario |
| `columns` | 1–6 panels per row |
| `net_total` | Black net-total dots on stacks |
| `shared_axes` | Share Y scales for comparable panels of the same property, collection, and unit |
| `filters` | Dimension names mapped to arrays of selected labels; empty means all |
| `colors` | Exact series labels mapped to six-digit hex colors |
| `series_order` | Ordered list of series labels for stable stack order |
| `scale`, `unit_label` | Display multiplier and optional resulting unit label, e.g. `0.001` and `TWh` for GWh |

The technology palette used by annual reports is also available here. Dataset
category aliases can be assigned their canonical colors explicitly in `colors`.
Unrecognized labels receive stable colors that persist across filters and panels.
The table retains reported units and unscaled values; plot scaling applies to
absolute values and differences only. Percent changes and ratios ignore physical
unit scaling. Their table unit column identifies the underlying reported unit.

## Comparison rules

Calculations happen **after the chosen pivot aggregation**:

- Difference: case minus baseline.
- Percent change: 100 × (case minus baseline) / baseline.
- Ratio: case / baseline.

The alignment retains exact property, collection, class, unit, phase, period,
time slice, sample, band, and displayed dimensions. Timestamp axes also retain
period end dates. Choose one reported model per scenario: model names are
preserved as provenance but may differ between solutions. Select model/sample
choices explicitly where a solution contains multiple reported series.

Missing measurements stay missing. Unmatched case/baseline rows and zero
denominators are marked in `comparison_status`; percentage/ratio results with
a zero baseline are undefined. Incomplete stacks and their net dots are hidden
instead of treating absent values as zero. Comparisons wait for query completion
and remain unavailable after query errors or cancellation.

Properties and units get separate panels. Component percentages and ratios are
not additive, so choose an unstacked view for those modes. Net dots describe the
selected, complete stack; hiding a legend item does not recalculate its total.
Use pivot filters to calculate totals for a different selection.

## Query cache and scale

`--cache-dir` enables an optional disk cache of **completed queries**, stored as
Parquet batches. The same query against the same source reuses those batches.
Local input size/timestamp changes invalidate its cache key. For Cloud solutions,
the key includes the solution ID and query; uncheck **Reuse complete cached
queries** and run again when you need fresh results.

Changing a plot, baseline, or display filter uses loaded data immediately. A
different query uses a different cache entry. Failed or cancelled source queries
are not published into the cache. Completed individual sources can be reused
after a later source fails. Refresh creates a new immutable cache generation;
old generations remain on disk, so use a dedicated cache folder that you can
remove when no sessions are reading it.

Queries are sequential, with a bounded queue and a shared row limit: 100,000
by default, up to 1,000,000 across all selected solutions. The live pivot still
holds those returned rows in memory. Prefer annual/category aggregates for many
solutions; dozens of full hourly datasets may exceed that limit. The chart
shows up to 120 panels and 100 series per panel, with explicit limit notes;
the table previews 1,000 rows. No chart limit silently changes the saved query.

## Offline snapshot

```powershell
.\pxbp.bat snapshot --workspace work/pivot-demo/workspace.private.json --output work/pivot-snapshot --cache-dir work/pivot-demo/cache
```

Choose a new output directory. Open `comparison.html` directly in a browser;
pan, zoom, hover, and legend hiding work without a server or internet connection.
Changing baseline, query, or chart settings requires reopening the workspace
in the live application or generating another snapshot. The output also includes
the full pivot in `comparison.parquet`, configuration, model metadata, and audit.
`complete.json` confirms successful export; files marked incomplete are unusable.

## Feature coverage

The modern viewer now supports scenario comparisons, six chart types, small
multiples, signed stacks/net dots, saved configurations, offline snapshots, and
cached multi-solution queries. Weighted calculations, chained advanced
operations, histograms, uncertainty ranges, area/line maps, and configurable
multi-section report bundles remain future work. The retained classic engine
contains reference implementations of those features.
