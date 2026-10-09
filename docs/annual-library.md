# Annual report library

The report library queries annual measurements and compares many solutions
against one baseline. Its default bundle contains nine reports: generation,
installed and new generator capacity, battery power and energy capacity,
emissions, curtailment, system cost, and generation cost. Each section shows
absolute values beside differences from the same baseline.

## Try the complete sample

Complete README Steps 1–3 first. Open PowerShell in your `pxbp` folder.
If a viewer is already running in that window, press **Ctrl+C** to stop it.
Paste these commands, pressing Enter after each:

```powershell
.\.venv\Scripts\python.exe examples/create-report-library-demo.py
.\pxbp.bat serve --bundle work/report-library-demo/bundle.private.json --cache-dir work/report-library-demo/cache
```

Keep PowerShell open. The browser opens at `http://localhost:5006/`, with the
**Reports** tab selected. These are four invented solutions, so no Cloud
account or PLEXOS installation is required.

1. Leave the nine choices in **Reports to include** selected.
2. Leave **Shared report baseline** set to **Baseline**.
3. Click **Build report bundle**. Wait for **9/9 sections fully available;
   216 queried rows**. The live viewer queries on demand; starting it alone
   does not load results.
4. Choose **Installed generator capacity** in **Display report section**.
   The left column shows GW; the right shows each solution's difference
   from Baseline, also in GW. Black dots show the net total of signed stacks.
5. Try **Battery energy capacity** (GWh), **Reported emissions** (reported
   mass units), and **Reported total system cost** (billions of reported dollars).
6. In **Scenarios to display**, choose one or two cases. An empty selection
   shows all queried cases. Display changes use loaded data; they do not query again.
7. To change the baseline or included reports, make the change and click
   **Build report bundle** again. Complete cached queries are reused by default.

If the sample folder already exists, skip its creation command. To create
a fresh sample, use `--output work/report-library-demo-2` on the first command
and use that folder on the launch command. `--cases 36` creates a larger sample.

## Save and reopen your choices

In **Reports**, click **Prepare report configuration**, then **Download report
configuration**. Keep the resulting `bundle.private.json` somewhere you can
find it. It includes source paths or Cloud IDs.

To reopen it, use the file chooser below the chart in **Reports**, select
your JSON file, and click **Build report bundle**. You can also launch it:

```powershell
.\pxbp.bat serve --bundle "C:\reports\bundle.private.json" --cache-dir work/report-cache
```

## Make a single report in the Pivot tab

1. Open **Query**, choose an **Annual report preset**, and click **Apply report
   preset**. This fills the collection, properties, annual period, units, and
   plot settings. Loaded bundle filters and colors carry over.
2. Check **Solutions to query**, model/sample/band filters, and date bounds.
3. Click **Run query**. Wait for completion; annual reports validate the raw
   asset/year measurements before showing charts.
4. In **Pivot**, change **Show**, baseline, chart type, panel count, or display
   filters. Percentage changes and ratios need an unstacked chart such as
   **Dot-Line**. Region and emission reports retain a panel for each object.
5. Save this view through **Workspace**. Its configuration remembers the
   annual preset, so reopening it performs the same validation and conversion.

Keep **X axis** set to `year` and **Pivot operation** to `sum` for library
reports. To run a different calculation, apply **Custom query** and run the
query again. Custom queries preserve their reported units.

## Use your own solutions

Start with the [comparison workspace guide](comparison-workspaces.md) to
discover local solution folders and create a workspace with named solutions,
a baseline, and explicit model/sample/band choices. For Cloud solutions,
use the [Cloud source guide](cloud-pivot.md). Mixed local and Cloud sources
use the same report presets.

With a loaded workspace, open **Reports**, choose reports and the shared
baseline, then click **Build report bundle**. Sources come from **Solutions
to query**, with the baseline included automatically. Shared filters carry
over phase, time slice, sample, model, band, and dates. Object/category/parent
filters are specific to a collection; put these in each section's configuration.

Alternatively, create a bundle configuration from a saved workspace:

```powershell
.\pxbp.bat bundle-config --workspace work/my-workspace.private.json --output work/my-bundle.private.json
.\pxbp.bat serve --bundle work/my-bundle.private.json --cache-dir work/report-cache
```

Annual presets default to **LTPlan / Year / Mean / Band 1 / All Periods**.
Check these against your solution's reported metadata. If multiple models
exist within a solution, choose the intended model. Every preset queries
unaggregated measurements, then validates distinct assets and annual years.

The report bundle has one row budget shared by all sections and solutions
(default 1,000,000). The single Query tab has its own row budget. An exceeded
budget stops processing; narrow dates, sources, or sections before retrying.
**Cancel** also stops a running bundle. A property that is not reported is
listed as unavailable; it is never converted to zero. Inspect section coverage
and missing comparison counts before interpreting differences.

## Export an offline HTML and printable PDF

After saving your bundle configuration, stop the server with Ctrl+C, then run:

```powershell
.\pxbp.bat bundle --spec work/report-library-demo/bundle.private.json --output work/annual-report --cache-dir work/report-library-demo/cache
Start-Process work\annual-report\reports.html
Start-Process work\annual-report\reports.pdf
```

The output folder must be new; choose another name if it already exists.
HTML includes its plotting resources and works offline. It initializes only
the selected section to keep large bundles usable. Its section selector,
hover, pan, zoom, and legend controls work without a server. Query or baseline
changes require rebuilding. The PDF contains an overview and report pages.

The folder also contains a saved private configuration, `audit.json`, raw
query Parquets, and absolute/difference Parquets for each available section.
`complete.json` distinguishes finished processing from all sections being
available. `INCOMPLETE.txt`, if present, means the export failed and its partial
files should not be used. These exports can contain private scenario names
and source locations; review them before sharing.

## Configure sections, views, colors, and filters

Edit the downloaded JSON in Notepad or the **Report bundle configuration**
box. Click **Apply report configuration** and **Build report bundle** after
editing. Sections appear in their configured order. Section IDs must be
unique and use letters, digits, hyphens, or underscores.

A section can look like this:

```json
{
  "id": "generation-lines",
  "title": "Generation by technology",
  "preset": "annual-generation",
  "views": ["Absolute", "Difference"],
  "plot": {
    "chart_type": "Dot-Line",
    "columns": 2,
    "shared_axes": true,
    "net_total": false
  },
  "query_filters": {"date_from": "2030-01-01", "date_to": "2040-12-31"}
}
```

Available chart types are **Line**, **Dot**, **Dot-Line**, **Bar**,
**Stacked Bar**, and **Stacked Area**. Views are **Absolute**, **Difference**,
**Percent change**, and **Ratio**. Percent/ratio sections require an unstacked
chart; zero or missing baseline values produce undefined comparisons.
Each section shares the top-level `baseline`; it cannot override it.

Set top-level `colors` to exact category/object/series labels and hex colors,
and `series_order` to the preferred legend/stack order. For example:

```json
"colors": {"Gas-CC": "#A6CEE3", "Short duration": "#FF4A88"},
"series_order": ["Gas-CC", "UPV", "Short duration"]
```

Built-in technology colors apply where labels are recognized. Unrecognized
labels receive stable colors; add explicit overrides for your preferred mapping.

List every preset with `.\pxbp.bat presets`. Use `bundle-config --presets`
with comma-separated IDs to choose the initial set. All 15 presets are:

| Preset ID | Measurement | Display unit |
| --- | --- | --- |
| annual-generation | Generator Generation | TWh |
| installed-capacity | Generator Installed Capacity | GW |
| new-capacity | Generator Capacity Built | GW |
| battery-power | Battery Generation Capacity | GW |
| battery-energy | Battery Installed Capacity | GWh |
| new-battery-power | Battery Generation Capacity Built | GW |
| new-battery-energy | Battery Capacity Built | GWh |
| battery-discharge | Battery Generation | TWh |
| battery-charge | Battery Load | TWh |
| emissions | Emission Production, per emission object | Reported mass unit |
| curtailment | Region Generation Curtailed, per region object | TWh |
| system-cost | Region Total System Cost, per region object | $B (reported) |
| generation-cost | Region Total Generation Cost, per region object | $B (reported) |
| generator-total-cost | Generator Total Cost | $B (reported) |
| generator-build-cost | Generator Build Cost | $B (reported) |

Power and energy capacities remain separate. Capacity is reported for each
year, not summed across years. Emission objects and region totals remain
separate to avoid mixing pollutants or adding overlapping totals. Cost presets
show distinct reported measures; they do not infer a cost breakdown, currency
year, discounted present value, or add build costs to total-cost fields.

Only compatible reported annual units are converted: MW to GW, generation
MWh/GWh to TWh, battery energy MWh to GWh, and dollars/thousands of dollars
to reported billions. Raw values, units, properties, and query selections
remain in the audit exports. Unknown units, duplicate asset/year rows, and
ambiguous model selections are rejected explicitly.

The library does not yet supply weighted averages, arbitrary expressions,
maps, or automatically inferred technology/geography mappings. Use the
existing asset-mapped reporting guides for geography-based reports.
