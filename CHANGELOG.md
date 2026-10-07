# Changes

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
