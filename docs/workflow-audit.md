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
