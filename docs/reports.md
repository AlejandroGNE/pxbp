# New capacity reports

The `report` command creates an interactive HTML file, a PDF and an asset-level
JSON audit. Both charts use the same technology colors. The HTML contains its
own Bokeh resources and works without an internet connection or a running server.

## Try the sample first

Open PowerShell in your PXBP folder. If you have already run the README viewer
walkthrough, run `setup.bat modern` again to install the PDF dependency.

```powershell
.\setup.bat modern
.\.venv\Scripts\python.exe examples\create-capacity-demo.py
.\pxbp.bat --config work/demo-capacity/sources.json report --spec work/demo-capacity/capacity-spec.json --output work/capacity-report
Start-Process work\capacity-report\capacity.html
Start-Process work\capacity-report\capacity.pdf
```

The sample compares two invented cases. Yellow means utility solar, blue means
onshore wind, and pink means battery power. In the HTML, choose **Build year**,
hover over bars and inspect **Annual totals** or **Methods**. Click legend items
to hide technologies. Hiding a technology changes its visibility; the hover
total remains the total across all technologies. The PDF includes regional totals,
annual timing and a methods page. It does not depend on browser printing.

To repeat a command, use a new output folder such as `work/capacity-report-2`.
The commands refuse to overwrite existing folders.

## If your solution is a ZIP without generated Parquet

For this report, PXBP can import the native annual **Units Built** summaries
included in a downloaded solution ZIP. This path reads the summaries in the ZIP
and writes Parquet directly; it does not create loose CSV files or convert the
full interval solution database. It supports annual builds only.

```powershell
.\pxbp.bat import-annual-zip --zip "C:\Results\Example Solution.zip" --output work/example-annual
.\pxbp.bat --parquet work/example-annual explore --collection SystemGenerators
```

Replace the ZIP path with your actual file. Your report queries must use
`"phase": "NativeAnnual"`, `"sample": "Native summary"`, `"period": "Year"` and
`"properties": "Units Built"`. These labels identify native annual summaries;
they are not a reconstructed phase or sample of the full solution database.
Add one source per imported solution to compare cases. Input MW ratings and
asset mappings are still required. `import-provenance.json` records the ZIP
checksum and source member names. The report audit copies this provenance.

If the ZIP does not contain the annual summaries, import fails with an
explanation. Use a full validated conversion or Cloud data instead. Full ZIP
conversion can consume substantial memory; run large conversions sequentially.

## Use real solutions

1. Create a sources configuration as described in the main README. Use local
   converted Parquet folders or Cloud solution IDs. Scenario labels do not imply
   that one case is a baseline.
2. Use `explore` to identify the reported annual build property, phase, sample,
   model and timeslice. Copy actual metadata names, including spaces. Prefer
   **Capacity Built** when reported in power units. For batteries,
   **Generation Capacity Built** is also supported as reported power. Otherwise
   use **Units Built**.
3. Copy the demo's `capacity-spec.json` outside the repository and edit its
   queries and asset mappings. Each queried collection needs its own query.
   Generator and battery objects may have the same name; identify them by both
   collection and object name.
4. Obtain asset regions, technology classifications and per-unit power ratings
   from the matching model inputs. Region, county, state and owner groupings
   need explicit, reviewed mappings. Do not assume a model Region is the desired
   reporting region. Do not guess missing boundaries from asset names.
5. Run the report command with your sources and specification, then review the
   audit before circulating the HTML/PDF.

An example query in `queries` is:

```json
{
  "collection": "SystemGenerators",
  "properties": "Units Built",
  "phase": "LTPlan",
  "period": "Year",
  "timeslice": "All Periods",
  "sample": "Mean",
  "model": "Example model"
}
```

An example entry in `assets` is:

```json
{
  "collection": "SystemGenerators",
  "object_name": "Example plant",
  "region": "Region A",
  "technology": "Gas-CC",
  "capacity_mw": 500
}
```

For a changing rating, supply `capacity_mw_by_year`, for example
`{"2030": 100, "2031": 150}`. Omit `capacity_mw` if every included year must have
an explicit rating. Data-file references, date bounds, scenario overrides,
expressions and input action operators must be resolved before supplying these
ratings. This command does not evaluate input-model logic.

For infrastructure proxy objects, replace region, technology and rating with
`"exclude_reason": "Infrastructure proxy; does not represent generation"`.
Excluded positive builds remain visible in `audit.json`.

Supported technology labels are `Nuclear`, `Coal`, `Gas-CC`, `Gas-CT`,
`Hydropower`, `Geothermal`, `Biopower`, `Onshore Wind`, `Offshore Wind`, `UPV`,
`DPV`, `Battery` and `Pumped Storage`. Expansion cohort categories are not
automatically treated as technologies.

## Combine model regions into reporting groups

Add `region_groups` to the report specification when several input regions
belong to one reporting group:

```json
"region_groups": {
  "Region A": "Group 1",
  "Region B": "Group 1",
  "Region C": "Group 2"
}
```

Every included asset region must have a mapping. The audit retains each asset's
`source_region` alongside its final reporting `region`. Grouping preserves
capacity totals. Validate older crosswalks against the current model's node,
region and zone memberships before using them. Asset technology/state tables
can become stale even when a regional crosswalk still agrees.

## Calculation and checks

The report sums annual additions once over the selected years. It converts
Capacity Built in MW, GW or kW to MW, or multiplies dimensionless Units Built
by an explicit per-unit MW rating. Battery capacity is power, not storage energy.
Net New Capacity and Installed Capacity are different measures and cannot be
substituted for annual builds.

The exporter rejects duplicate asset/year rows, mixed query dimensions,
nonfinite/negative additions, missing positive-build mappings, missing ratings,
unsupported units and incomplete queries caused by the row limit. A zero value
does not require a mapping; any positive build does. It uses one reported
sample/model/band, not a statistical aggregation of several samples.

Keep private source configurations, real asset mappings and generated reports
outside the public repository. The audit contains asset names and source paths
or solution IDs. Check that all component queries have the intended scope;
an omitted collection or an explicit asset filter cannot be detected as an
unreported asset universe.

This release supports annual new capacity by one explicit region grouping.
Installed capacity, additional geography views, cost measures, maps and flowgate
exploration remain separate report features.
