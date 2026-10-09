# PXBP — PLEXOS BOKEH PIVOT

PXBP lets you query PLEXOS results and compare scenarios in charts and tables.
You choose the data to load, then adjust the chart in your web browser.

**Start with the sample-data walkthrough below.** You do not need PLEXOS,
a Cloud account, or your own solution files to try it. These instructions are
for **64-bit Windows**. No programming experience or Conda is required.

## Compare many solutions against a baseline

After installing PXBP using Steps 1–3 below, try the comparison workspace:

```powershell
.\.venv\Scripts\python.exe examples/create-pivot-demo.py
.\pxbp.bat serve --workspace work/pivot-demo/workspace.private.json --cache-dir work/pivot-demo/cache
```

Keep PowerShell open and press **Run query** in the browser. Wait for
**Complete. 540 result rows.** You will see 36 fictional solutions as technology
stacks, with differences against **Baseline** and black net-total dots.

In **Pivot**, change **Show** between absolute values and differences, choose
another **Baseline**, or choose **Scenario stacks**, **Scenario areas**, or
**Technology comparisons** from **View preset**. These changes use loaded data.
For percentage changes or ratios, use an unstacked view.

In **Workspace**, press **Prepare current configuration**, then **Download
displayed configuration**. Reopen that JSON file using the file chooser to
restore solutions, query, baseline, filters, chart type, colors, and layout;
press **Run query** to load its data.

See the [comparison workspace walkthrough](docs/comparison-workspaces.md) for
your own solution folders, adding solutions, configuration options, caching,
and offline chart snapshots. If the demo folder already exists, pass a new
`--output` folder to the first command and use that folder in the second.

## Step 1 — Install two prerequisites

If both are already installed, check them as described below and continue.

1. Install **Python 3.12**. The tested installer is on the
   [Python 3.12.10 download page](https://www.python.org/downloads/release/python-31210/).
   Scroll to **Files**, choose **Windows installer (64-bit)**, and open the
   downloaded installer. Enable **Add python.exe to PATH** and leave the
   Python launcher option enabled, then select **Install Now**. PXBP's setup
   requires Python **3.12**; choosing a different major/minor version will fail.
2. Install **Git for Windows** from the
   [official download page](https://git-scm.com/install/windows).
   Choose the x64 installer. During installation, keep the option that allows
   Git to run from the command line and other software; the remaining defaults
   are suitable. Git downloads one of PXBP's required components during setup.
3. Close any PowerShell windows that were open before installation. Open a new
   one: click the Windows **Start** button, type **PowerShell**, and open it.
4. Paste each command below into PowerShell and press **Enter** after each one:

   ```powershell
   py -3.12 --version
   git --version
   ```

   You should see `Python 3.12.x` and a Git version. If a command is not
   recognized, see **Troubleshooting** below before continuing. On a managed
   work computer, use your organization's approved installation process.

## Step 2 — Get PXBP and open its folder

**If you already have the new `pxbp` folder on your computer**, skip the download:
open that folder in File Explorer, click its address bar, type `powershell`,
and press **Enter**. Continue to Step 3.

For a first download:

1. In **File Explorer**, open **Documents**.
2. Click the address bar at the top, type `powershell`, and press **Enter**.
   This opens a command window in that folder.
3. Paste this command and press **Enter**:

   ```powershell
   git clone https://github.com/AlejandroGNE/pxbp.git
   ```

   Wait until the download finishes and the prompt returns. The download
   includes example files and project history, so it may take several minutes.
4. Enter the downloaded folder:

   ```powershell
   cd pxbp
   ```

5. Check that you are in the right place:

   ```powershell
   dir setup.bat
   ```

   It should list a file named `setup.bat`. In File Explorer, this same folder
   contains `README.md`, `pxbp.bat`, and the `examples` folder.

**For every command below, use this PowerShell window in the `pxbp` folder.**
Copy only the text inside a command box. The `PS C:\...>` prompt already shown
in your window is not part of the command.

## Step 3 — Set up the viewer once

Paste this command and press **Enter**:

```powershell
.\setup.bat modern
```

Wait for it to finish. It downloads the required packages into a folder named
`.venv` inside PXBP. You do not need to open that folder or activate anything.
Successful setup ends with lines containing **pxbp OK** and **Ready: modern**.
If it says **Setup failed**, resolve that error before continuing.

Check the installation:

```powershell
.\setup.bat modern --check
```

You should again see **pxbp OK** and **Ready: modern**. Setup is needed only
once on this computer, or again after an update that changes dependencies.

## Step 4 — Open a demo with sample data

Create the sample files:

```powershell
.\.venv\Scripts\python.exe examples/create-demo.py
```

It prints a path ending in `work\demo-parquet\sources.json`. This creates two
fictional scenarios, **Demo baseline** and **Demo alternative**. It does not
use your PLEXOS files or contact PLEXOS Cloud.

Launch the viewer:

```powershell
.\pxbp.bat --config work/demo-parquet/sources.json serve
```

A browser should open at **http://localhost:5006/**. If it does not open,
copy that address into your browser. **Keep the PowerShell window open** while
you use the viewer; it runs the application.

## Step 5 — Make your first chart

1. In the browser, leave the default query settings unchanged. Both demo
   scenarios should be selected in **Solutions to query**.
2. Click **Run query** near the top. The **Pivot** tab opens while results load.
3. Wait for **Complete. 192 result rows.** You should see a chart and table
   comparing the two scenarios.
4. In the **Pivot** tab, change **Series** to `category_name` to compare Gas
   and Wind. Change **Chart** to **Bar** to try a different display.
5. Use **Filter scenario** to show one scenario. An empty filter means all
   scenarios. Chart and filter changes use the already-loaded data; you do
   not need to click **Run query** again unless you change the query itself.

The demo uses synthetic values. Use the next section when you are ready to
query real solutions.

## Step 6 — Stop and reopen PXBP

To stop the viewer, return to PowerShell and press **Ctrl+C**. If Windows asks
`Terminate batch job (Y/N)?`, enter `Y`. Closing the browser alone does not stop
the application.

Next time, open your `pxbp` folder in File Explorer, type `powershell` in its
address bar, and run:

```powershell
.\pxbp.bat --config work/demo-parquet/sources.json serve
```

Do not recreate the demo files each time. If the creation command says
**Choose a new output directory**, the demo folder already exists; simply run
the launch command above.

## Use your own PLEXOS results

Choose the route that matches the files or access you have:

| What you have | What to do |
| --- | --- |
| A converted PLEXOS solution folder containing Parquet files | Use **Local Parquet** below. No Cloud login or native PLEXOS API is needed. |
| Solutions available in PLEXOS Cloud | Use **Cloud solutions** below. You need the Cloud CLI and access to those solutions. |
| Only a solved PLEXOS solution ZIP | Convert it to Parquet with the Cloud CLI, or use the native ZIP extraction workflow linked below. |
| Only a model input XML | Solve the model in PLEXOS first. A model input file does not contain solved results. |

### Local Parquet

1. Find the converted solution folder in File Explorer. It must contain
   `fullkeyinfo`, `data`, and `period` folders with `.parquet` files inside.
   Select the solution folder itself, not an individual `.parquet` file.
2. Copy the folder's full path from File Explorer's address bar.
3. Replace `C:\models\my-solution` in this command with that path. Keep the
   quotation marks, especially if the path contains spaces:

   ```powershell
   .\pxbp.bat --parquet "C:\models\my-solution" serve
   ```

4. In the browser's **Query** tab, click **Explore collection**, then open
   **Reported choices** to see what the first selected solution actually
   contains. Set **Properties**, **Phase**, **Period**, and **Time slice** in
   the Query tab to match those choices, then click **Run query**. The demo's
   defaults are not guaranteed to be present in your own solution.

To compare two local solutions, replace both example paths:

```powershell
.\pxbp.bat --parquet "C:\models\baseline" --parquet "C:\models\alternative" serve
```

Local queries read Parquet directly, without CSV intermediates. For converting
ZIPs, naming scenarios, or mixing local and Cloud sources, see the
[local Parquet guide](docs/local-parquet.md).

### Cloud solutions

1. Obtain **PLEXOS Cloud CLI** through your normal PLEXOS/IT installation
   process and sign in using your organization's instructions. PXBP's setup
   does not install the CLI or sign you in.
2. Confirm that PowerShell recognizes it:

   ```powershell
   plexos-cloud solution sql --help
   ```

3. Obtain the **solution ID** for a solved result you can access. This is a
   solution UUID, not its display name or a model XML filename. Ask your
   PLEXOS Cloud administrator if you do not know where to find it.
4. Replace `YOUR-SOLUTION-ID` with the actual ID, keeping the quotes:

   ```powershell
   .\pxbp.bat --solution-id "YOUR-SOLUTION-ID" serve
   ```

5. Click **Explore collection**, inspect **Reported choices**, choose matching
   query settings, and click **Run query**. Check the reported choices of each
   solution before comparing them; exploration shows the first selected one.

For multiple solution IDs and query troubleshooting, see the
[Cloud guide](docs/cloud-pivot.md).

### Native ZIP extraction and the classic viewer

This route requires an installed Windows PLEXOS API and more preparation.
It extracts CSV files and offers the classic ReEDS chart presets and reports.
Follow the [native ZIP and classic viewer guide](docs/native-csv.md) for its
separate setup, mappings, extraction, and viewer steps. The sample walkthrough
above uses the modern viewer, which does not require these extra steps.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `py` or Python 3.12 is not found | Install Python 3.12 with the launcher enabled, then close and reopen PowerShell. Check `py -3.12 --version`. |
| `git` is not recognized | Install Git for Windows with command-line access enabled, then close and reopen PowerShell. Check `git --version`. |
| `setup.bat` or `pxbp.bat` is not found | Open the folder containing those files. Use `dir setup.bat` to check. Commands must begin with `.\`. |
| **Environment missing** | Run `.\setup.bat modern` and wait for **Ready: modern**. |
| Demo creation says **Choose a new output directory** | The demo files already exist. Skip creation and launch using `work/demo-parquet/sources.json`. |
| The browser does not open | Open the printed `http://localhost:.../` address yourself. Keep PowerShell open. |
| Port 5006 is already in use | Stop the earlier viewer with Ctrl+C, or add `--port 5007` after `serve` and open `http://localhost:5007/`. |
| A blank page, or PowerShell says **Refusing websocket connection** | Open `http://localhost:5006/` (use your chosen port). If the address starts with `127.0.0.1`, replace it with `localhost`. Keep PowerShell open and refresh. Update PXBP below to fix automatic browser opening in older versions. |
| Missing Parquet tables | Choose the solution folder containing all three required table folders, not a single file or its parent directory. |
| Empty results or an unsupported choice | Use **Explore collection** and match the reported names and dates. Confirm that the selected solution contains those results. |
| Cloud says solution data is being prepared | Wait for the service to prepare it and retry. A completed resource can still be unavailable for queries. |
| IT blocks Python or a required program | Give IT the blocked executable path and message so they can approve it through your normal process. |

If you need help, [open an issue](https://github.com/AlejandroGNE/pxbp/issues)
with the command you ran and the error message. Do not include passwords,
tokens, or private solution files.

## Update an existing installation

Stop the viewer with **Ctrl+C**, then run these commands from the `pxbp` folder:

```powershell
git pull --ff-only
.\setup.bat modern
.\setup.bat modern --check
```

Then launch it again. If Git reports local changes, keep your changes and ask
for help resolving them before updating.

## More detailed guides

- [Cloud queries](docs/cloud-pivot.md)
- [Direct local Parquet queries](docs/local-parquet.md)
- [Native ZIP extraction and classic ReEDS viewer](docs/native-csv.md)
- [Environment setup and interpreter selection](docs/python-environments.md)
- [Changes](CHANGELOG.md) and [validation record](docs/workflow-audit.md)

## Create an HTML and PDF capacity report

Start with this small sample report after completing Steps 1–3 above. If you
already installed PXBP, rerun setup to add the PDF renderer. In the same
PowerShell window, paste each command and press Enter:

```powershell
.\setup.bat modern
.\.venv\Scripts\python.exe examples\create-capacity-demo.py
.\pxbp.bat --config work/demo-capacity/sources.json report --spec work/demo-capacity/capacity-spec.json --output work/capacity-report
Start-Process work\capacity-report\capacity.html
Start-Process work\capacity-report\capacity.pdf
```

The browser opens a report comparing two invented cases. Choose a build year
and hover over the chart to inspect new capacity. The PDF opens separately.
Both files use consistent technology colors. The HTML works offline.

These commands create `work/capacity-report/audit.json` as well, which records
the calculations and exclusions. If a sample or report folder already exists,
choose a new output name; existing files are never overwritten.

For your own solutions, follow the [capacity report guide](docs/reports.md).
It explains the required asset mapping, per-unit MW ratings, exclusions and
query selections. This first report covers annual new capacity; the other
report types are still under development.

## Installed capacity, costs, energy and flowgates

Follow the [annual reporting guide](docs/annual-reports.md) to select properties
from a downloaded solution ZIP directly into Parquet, map current owner/state
geography, and export an offline dashboard and PDF. Existing local-Parquet and
cloud sources use the same report specifications. Native ZIP extraction needs
a compatible installed PLEXOS API and the optional native Python extra; it does
not require Conda.
