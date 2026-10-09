# Changes

## 0.8.0 � Analytical workspaces

- Add 79 annual, interval, monthly, duration, heatmap, profile, distribution,
  statistics, and calculated report recipes with shared scenario baselines.
- Add a GUI report editor for titles, charts, comparison views, section order,
  duplication, colors, series order, and safe calculated annual measures.
- Calculate physical energy and weighted averages from explicit durations;
  retain partial coverage, missing operands, native mass units, and zero-denominator status.
- Reuse unique measurements and complete cached queries within explicit row budgets.
- Export lazy offline HTML, bookmarked vector PDF, queried/calculated Parquets,
  configurations, and calculation/coverage audits.
- Add fictional multi-solution data and a beginner walkthrough.

## 0.7.0 — Annual comparison reports

- Add 15 annual query/plot presets and a nine-section comparison library.
- Build live report bundles with a shared baseline, section selector,
  scenario filters, cache reuse, row budgets, cancellation, and saved configs.
- Export offline HTML, vector PDF, raw/pivot Parquets, and coverage audits.
- Validate asset/year identity and reported units before converting power,
  energy, and cost measures. Keep emission and region objects separate.
- Add a four-solution sample and step-by-step README/report instructions.

## 0.4.1

- Support explicit region-to-reporting-group crosswalks while retaining original
  asset regions in the audit and rejecting incomplete mappings.
- Accept reported battery Generation Capacity Built in power units.

## 0.4.0

- Add audited annual new capacity reports with offline HTML, vector PDF,
  consistent technology colors, scenario/year selectors and asset-level audit.
- Import native annual build summaries from solution ZIPs directly into
  queryable Parquet with source checksums and explicit provenance.
- Add a synthetic report walkthrough and checks for unit conversion, missing
  mappings, duplicate samples and infrastructure proxy exclusions.


## Unreleased — standard Python setup

* Replace Conda/Miniforge batch setup and activation with CPython 3.12, venv and pip.
* Keep separate native, classic Bokeh 2.4 and modern Bokeh 3 environments.
* Launchers resolve absolute paths and propagate setup/process failures.
* Classic report workers use the viewer interpreter with structured arguments.
* Remove an unused debugger import and obsolete Conda environment YAML files.

## 0.3.0 — Local Parquet and mixed sources

* Direct local PLEXOS Parquet queries with DuckDB batches and no CSV intermediates.
* Multiple local scenarios and mixed Cloud/local sessions use the same selections and pivot.
* Configuration paths resolve relative to the configuration file.
* Local cancellation interrupts DuckDB, with timeout and schema validation.
* Result batches retain source kind and local path as well as scenario/Cloud ID.

## 0.2.0 — Cloud pivot

* Separate `pxbp` package and current Bokeh server application.
* On-demand queries against multiple Cloud solution IDs through installed CLI.
* Report exploration, exact object selection, filters and category/object/period aggregation.
* Progressive batches, optional disjoint date windows, cancellation, timeouts and explicit overflow errors.
* In-memory scenario pivots preserving reported series identity and complete timestamps.
* Corrected legacy setup/configuration/output guidance and recorded live checks.
