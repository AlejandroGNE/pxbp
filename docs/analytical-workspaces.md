# Analytical workspaces

The **Analytics** tab builds a report from annual and interval measurements,
with one baseline shared across every section. It contains 79 recipes and a
report editor. Start with three solutions and a week of interval data; expand
the dates or source list after checking coverage.

## Try every feature with sample data

Complete README Steps 1–3. Open PowerShell in the folder containing `pxbp.bat`.
Stop an existing viewer with **Ctrl+C**. Paste each command and press Enter:

```powershell
.\.venv\Scripts\python.exe examples/create-analysis-demo.py
.\pxbp.bat serve --analysis work/analysis-demo/analysis.private.json --cache-dir work/analysis-demo/cache
```

Keep PowerShell open. The browser starts in **Analytics** with three fictional
solutions. No Cloud account or installed PLEXOS is needed. If the sample folder
already exists, skip its creation command; use a new `--output` folder to create
another sample.

1. Click **Build analysis** and wait for **79/79 sections fully available**.
2. Choose **Generator dispatch** in **Analysis section**. Technology stacks
   show absolute dispatch beside changes from Baseline, in GW.
3. Try **Regional price**, **Battery discharge and charging balance**, and
   **Battery state of charge**. Charging is negative in the balance plot.
4. Try **Monthly load energy**, **Load-weighted monthly price**, **Load duration
   curve**, **Price calendar heatmap**, and **Load versus price**. The sample
   spans January 30 through February 2, so its monthly results are partial
   subtotals, not complete monthly totals.
5. Choose one or two **Display cases** to simplify the chart. Empty means all.
   Display filtering keeps the baseline available for calculation.
6. Choose another **Analysis baseline**. If that case was already queried,
   comparisons update from loaded measurements without another query.
7. To load different dates, solutions, annual years, regions, or recipes,
   open **Query settings**, change those controls, and click **Build analysis**. The baseline is always
   included. The default selection queries LTPlan / Mean / Band 1 / All Periods.
8. The heading reports undefined metrics, partial months, and incomplete input
   coverage. Read these before interpreting the chart. Missing inputs are
   never silently filled with zero.

## Edit the report without writing JSON

Select an **Analysis section**, then click **Report editor**:

- Change its title, chart, layout, panel count, or comparison views; click **Apply
  section styling**. Generator-category reports offer scenario panels or technology panels.
  Available views are Absolute, Difference, Percent change,
  and Ratio. Choose an unstacked chart for percentage changes and ratios.
- **Move section up/down**, **Duplicate section**, and **Remove section** change
  report order and contents. These choices are saved in the configuration.
- Choose a **Series color**, pick a color, and click **Set color**. **Use default
  color** removes that override. Technology defaults and supplied palettes are
  preserved; signed battery series inherit their object's color.
- Enter exact labels under **Preferred series order**, one per line, and click
  **Apply series order**. Unlisted series follow the named ones.
- Click **Calculated measures**, then under **Calculated annual section**, select two reported measures from the
  same class, a calculation, and object or generator-category scope. Click
  **Add calculated section**, then **Build analysis**. Supported operations are
  A/B, A−B, 100×A/(A+B), and a weighted mean of A using B. No Python expression
  is executed. Units are derived from normalized base units; for example,
  generator cost divided by generation yields $/MWh.

Plots preserve recipe calculations and object identities. Scatter recipes use
Absolute only. Calendar heatmap recipes can use heatmaps or ordinary charts;
other interval recipes retain their original time resolution. Changing a
chart never changes its physical aggregation.

Click **Save / open**, then **Prepare analysis configuration** and **Download analysis
configuration**. Save the file somewhere you can find it. Reopen it with the
file chooser under **Save and reopen**, then click **Build analysis**. Loading
a file alone never runs queries. The file contains private source paths or
Cloud IDs; keep it out of public repositories.

## Use existing workspaces and real solutions

First follow the [comparison workspace guide](comparison-workspaces.md) to
discover converted local solution folders, label them, and select a baseline.
The [Cloud guide](cloud-pivot.md) explains solution IDs and CLI setup. Both
source types use the same analytical recipes.

Convert an existing workspace into a report configuration, substituting its
filename and dates that are reported in your solutions:

```powershell
.\pxbp.bat analysis-config --workspace work/my-workspace.private.json --from 2030-01-01 --to 2030-01-07 --output work/my-analysis.private.json
.\pxbp.bat serve --analysis work/my-analysis.private.json --cache-dir work/analysis-cache
```

Use `--bundle work/my-bundle.private.json` instead of `--workspace` to start
from an annual report bundle. Shared phase/sample/model/band/time-slice filters,
colors, series order, selected sources, and baseline carry over. Collection
filters do not carry into unrelated classes. Annual bounds are independent of
the interval window; set **Annual first/last year** in the GUI if needed.

The default configuration includes 28 recipes spanning each feature family.
Add `--presets all` to include all 79, or `--presets duration-price,monthly-load`
for a small report. `pxbp.bat analysis-presets` lists IDs and readable titles.
Use an exact **region object** if you need one denominator for emission
intensity; multiple regional totals are kept separate and never added.

An interval workspace supports up to 366 days in local model time. Query
filters default to one phase, sample, band, and time slice. Each solution must
resolve to one reported model; specify `query_filters.model` in its private
configuration when needed. Model names are retained as provenance and are not
used to match different scenarios to each other.

## Export a portable report

After downloading your configuration, use its actual saved filename below:

```powershell
.\pxbp.bat analysis --spec work/analysis-demo/analysis.private.json --output work/analysis-report --cache-dir work/analysis-demo/cache
Start-Process work\analysis-report\analysis.html
Start-Process work\analysis-report\analysis.pdf
```

The output directory must be new. The HTML contains its plotting resources,
works offline, and renders only the selected section. The PDF contains vector
charts, all configured views/facets, and section bookmarks; a complete library
can produce many pages. Dense interval PDF stacks use a net-total line with
spaced dots; full values remain in the HTML and Parquets. Reduce the recipe list
to create a focused deliverable.
Offline reports keep the queried baseline fixed; reopen the configuration in
the live viewer to change it.

The export also writes the saved configuration, `audit.json`, untouched queried
input Parquets, each section's compared values, and `complete.json`. Inspect
`all_sections_available` and the section audit: successfully finishing an
export does not mean every property was reported. `INCOMPLETE.txt` identifies
a failed export and partial output that should not be used.

## Calculations and interpretation

| Recipe family | Calculation and boundaries |
| --- | --- |
| Interval power | Reported MW converted to GW; distinct generator assets are summed within reported categories. |
| Monthly energy | Sum(MW × interval hours), then convert MWh to GWh/TWh. Reported interval money/mass amounts are summed once, without multiplying by hours. |
| Monthly/daily profiles | Duration-weighted means over observed intervals. Load-weighted price uses load MW × duration as the weight. |
| Month/hour boundaries | Split crossing intervals at calendar boundaries. Power/price are treated as constant within each reported interval; interval money/mass amounts are allocated in proportion to its duration. |
| Duration curve | Descending duration-weighted distribution at 101 exceedance percentages. Differences compare the same percentile coordinates, not simultaneous hourly differences. |
| Histogram | Common price bins across selected scenarios; heights measure observed hours, not numbers of rows. |
| Generation share | Category generation / total reported generator generation; no renewable classification is inferred. |
| Nominal utilization | Annual generator MWh / (installed MW × calendar-year hours), including leap years. This differs from a reported capacity factor. |
| Reported capacity factor | Installed-capacity-weighted reported asset capacity factors. Incomplete asset/weight sets are undefined. |
| Weighted costs | Generation-weighted reported levelized cost or short-run cost; the source's cost definition is retained. |
| Storage duration/cycles | Installed MWh / generation MW; annual discharged MWh / installed MWh gives discharge-equivalent cycles, not counted physical events. |
| Cost intensity | Reported cost / matching reported energy. Total, build, fixed, and annualized costs remain distinct; no discounting, inflation, or cost decomposition is inferred. |
| Emission intensity | Native reported mass / the selected region's generated MWh. No conversion between pounds, short tons, or metric tonnes is inferred. |
| Capacity change | Current installed capacity minus the previous calendar year's value; first-year change is undefined. This is net change, not inferred retirement. |
| Observed unserved load | Integrated reported unserved MW, hours with positive unserved load, and longest contiguous observed event. Gaps break events. These are not probabilistic reliability estimates. |

Difference uses the original unit; differences of percentages are **percentage
points**. Percent change is 100×(scenario−baseline)/baseline; Ratio is
scenario/baseline. Zero denominators, missing measurements, and ambiguous
identities stay undefined and retain comparison status. Baseline differences
are zero wherever the underlying metric is defined.

Intervals need explicit positive start/end durations and must not overlap.
Dates use the model's local clock without timezone suffixes; this version does
not infer daylight-saving adjustments. Monthly subtotals are marked partial
unless every hour of that calendar month is observed. Statistics describe the
selected observations; they do not extrapolate missing hours. Annual reports
use calendar-year labels independently of the interval selection.

Unique measurements are queried once per build and reused by recipes. Complete
disk-cache entries can be reused in later builds. The default total budget is
2,000,000 rows, adjustable up to 10,000,000; each source/measurement request is
also limited to 1,000,000 rows. Budget or timeout failures stop the build.
Narrow dates, sources, or recipes before retrying. **Cancel analysis** stops a
running job. An unavailable property is listed explicitly rather than guessed.
