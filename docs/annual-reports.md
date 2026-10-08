# Annual capacity, costs, energy and infrastructure reports

These reports use selected annual properties. They export an offline dashboard,
a PDF of annual comparisons, and Parquet files containing the underlying
asset-level values. Keep your source configurations, mappings and outputs in a
private folder outside this repository.

## Try the reports without downloading a solution

After completing the Python setup in the main README, run:

```powershell
.\.venv\Scripts\python.exe examples/create-annual-demo.py
.\pxbp.bat --config work/demo-annual/sources.json report --spec work/demo-annual/report-spec.json --output work/demo-annual-report
Start-Process work/demo-annual-report/reports.html
```

This creates synthetic capacity, cost, energy, reserve-margin and flowgate
views for two cases. The output folder must be new each time.

## Start with a downloaded solution ZIP

You need Windows, the Python environment from the main README, and a compatible
installed PLEXOS API. The cloud and existing-Parquet workflows do not need that
API. Native ZIP extraction additionally needs pythonnet; it does not use Conda.

1. Open PowerShell in the repository folder. Install the native extra:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[native]"
   ```

2. Save a file named `annual-properties.json` in your private working folder:

   ```json
   {
     "years": [2031, 2032],
     "collections": {
       "SystemGenerators": ["Capacity Built", "Installed Capacity", "Build Cost", "Annualized Build Cost", "Total Cost", "Generation"],
       "SystemBatteries": ["Generation Capacity Built", "Generation Capacity", "Build Cost", "Total Cost"],
       "SystemZones": ["Load", "Imports", "Exports", "Capacity Reserve Margin"],
       "SystemInterfaces": ["Flow", "Rental Total", "Fixed Flow Violation Cost"]
     }
   }
   ```

3. Run the following command. Replace the ZIP, specification, output and API
   paths with paths on your computer. The output must be a new folder.

   ```powershell
   .\.venv\Scripts\python.exe -m pxbp import-native-annual --zip "C:\Reports\Solution.zip" --spec "C:\Reports\annual-properties.json" --output "C:\Reports\annual-parquet" --api-path "C:\Program Files\Energy Exemplar\PLEXOS 11.0 API"
   ```

   Opening a large solution can take several minutes. Progress lines show the
   collection, years and returned row counts. Extraction starts with one year,
   then batches contiguous years within the row budget. If a query exceeds the
   budget, request fewer properties. Only the selected LT Plan annual results
   are imported; this is not a full solution conversion. No CSV intermediates
   are created. Collection IDs are resolved from the solution by name.

   API compatibility depends on the installed runtime. Use a compatible API
   folder containing `PLEXOS_NET.Core.dll`; a desktop installation folder is
   not necessarily an interchangeable API installation. Missing-property
   coverage, source checksum and selections are saved in
   `import-provenance.json`. Query failures stop the import.

4. Create a source configuration as described in the main README, pointing
   its `path` at `C:\Reports\annual-parquet`. Repeat extraction for additional
   solutions, with a separate output folder and unique scenario label for each.

## Define the reports and geography

Save a second JSON file, for example `annual-report.json`:

```json
{
  "title": "Annual solution reports",
  "years": [2031, 2032],
  "assets": [
    {
      "collection": "SystemGenerators",
      "object_name": "Plant A",
      "technology": "Gas-CC",
      "sector": "Generation",
      "planning_region": "North",
      "owner": "Owner A",
      "state": "State A",
      "mapping_status": "current model"
    }
  ],
  "metrics": [
    {
      "id": "installed_power",
      "title": "Installed power capacity",
      "section": "Capacity",
      "family": "power",
      "temporal": "snapshot",
      "sectors": ["Generation"],
      "queries": [
        {"collection": "SystemGenerators", "properties": "Installed Capacity", "phase": "LTPlan", "period": "Year", "timeslice": "All Periods", "sample": "Mean"},
        {"collection": "SystemBatteries", "properties": "Generation Capacity", "phase": "LTPlan", "period": "Year", "timeslice": "All Periods", "sample": "Mean"}
      ]
    }
  ]
}
```

Add asset mappings for every collection/object identity that you want to group.
Use current model memberships before an older workbook crosswalk when they
conflict. Retain the mapping source in `mapping_status`; confirm current state
information where available and use older exact matches only as a fallback.
An object's electrical owner assignment does not by itself establish its state.
Missing mappings stay visible as `Unassigned` and `Other`; values are retained.
The exporter cannot infer or validate geography from an asset name.

Add more metric objects to `metrics`, with unique IDs. Supported unit families:
`power` (GW), `energy` (TWh), `money` ($B), `count`, `hours`, `percent`, and
`native` (unchanged reported unit). Unsupported or mixed units stop the export.
The `temporal` rule is `sum` for annual additions, costs and energy, or
`snapshot` for installed capacity and ratios. Ratios and native units retain
individual objects rather than being summed across regions.

Set `asset_detail` to `true` and `geographies` to `["object_name"]` for an
asset explorer. Charts show up to 20 ranked objects; the table retains all
objects, and its search filters the chart when grouped by object. Otherwise the dashboard table displays geography/technology
group totals, while the audit Parquet retains full asset detail. Large asset
explorers make larger HTML files; choose only the metrics you need.

Useful reported properties, subject to the solution's reporting settings:

| Collection | Report | Property | Rule |
|---|---|---|---|
| Generators | New capacity | Capacity Built | sum, power |
| Batteries | New battery power | Generation Capacity Built | sum, power |
| Generators | Installed capacity | Installed Capacity | snapshot, power |
| Batteries | Installed battery power | Generation Capacity | snapshot, power |
| Generators/Batteries | Upfront construction cost | Build Cost | sum, money |
| Generators/Batteries | Annual construction charge | Annualized Build Cost | sum, money |
| Generators/Batteries | Reported asset total cost | Total Cost | sum, money |
| Generators | Operating generation cost | Total Generation Cost | sum, money |
| Generators/Batteries | Fixed operating cost | FO&M Cost | sum, money |
| Generators/Batteries | Gross generation | Generation | sum, energy |
| Batteries | Charging energy | Load | sum, energy |
| Zones | Load and interchange | Load, Imports, Exports | separate sum, energy metrics |
| Zones | Reserve margin | Capacity Reserve Margin | snapshot, percent |
| Interfaces | Flowgate energy | Flow | verify reported energy unit |
| Interfaces | Flowgate rental total | Rental Total | verify reported money unit |
| Lines | Congestion duration | Hours Congested | sum, hours |
| Generators/Lines | Expansion timing | Units Built | sum, count |

Generator proxy objects may represent transmission or gas expansion. Give them
distinct `sector` and `technology` mappings and filter capacity/generation
metrics with `sectors: ["Generation"]`. Cost reports can include all sectors or
show each separately. Never add upfront Build Cost to a Total Cost that already
contains Annualized Build Cost. Generator and battery cost totals are the sum
of those selected assets, not automatically the complete engine objective.
Zones can overlap, so summing zonal values is not automatically a system total.
The exporter does not apply an implicit discount rate or terminal perpetuity.

## Export and open

```powershell
.\pxbp.bat --config "C:\Reports\sources.json" report --spec "C:\Reports\annual-report.json" --output "C:\Reports\annual-report-output"
Start-Process "C:\Reports\annual-report-output\reports.html"
```

Choose a measure, scenario, grouping and year. Installed capacity always shows
one year. Search the detail table to find an asset. Open `reports.pdf` for annual
comparison pages. `audit.json` connects metric IDs to asset-value Parquet files,
source imports and property coverage. A missing property is not a zero. Check
coverage before comparing cases; filtered objects and individual missing rows
still require an independent completeness check.

Annual flowgate summaries do not reconstruct hourly congestion, binding
intervals, physical locations or upgrade-to-flowgate relationships. Those
features need reported interval properties and explicit current model links.

An explicit current crosswalk can set `report_object_name` on an asset mapping
and `object_label: "mapped"` on a metric to group upgrade-proxy spending under
its linked flowgate identifier. Missing mapped labels stop the export. Audit
Parquet retains `source_object_name` alongside the reporting label. Validate
these links from current input memberships; similar names are not evidence of
a relationship. Some models represent flowgates as Constraints instead of
Interfaces. Use their reported units for activity/RHS/slack/price; a dimensionless
constraint value cannot silently become MW.

Use an optional `related_asset` field to expose a shared physical upgrade asset
for several constraint variants. Search matches both the reported object and
its related asset. Keep each variant's results separate; copy the upgrade cost
only once under the upgrade asset's reporting label. Cost measures are separate
views, not an additive list: operating totals can already include emissions or
fuel costs, while Total Cost can already include annualized construction cost.
