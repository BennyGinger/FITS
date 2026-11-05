<p align="center">
  <img src="assets/fits_logo.png" alt="FITS logo: fluorescent cells and tracking trajectories forming a fish" width="480">
</p>

<p align="center">
  <img src="assets/fits_title.svg" alt="Fluorescent Image Tracking Software" width="900">
</p>

FITS—Fluorescent Image Tracking Software—is a reproducible workflow for
processing and quantifying fluorescence-microscopy experiments. It brings image
conversion, registration, background subtraction, segmentation, tracking,
spatial profiling, and labeled-region extraction into one experiment-aware
pipeline.

The project is aimed at researchers who should not need to write Python to run
an analysis. Its desktop interface exposes pipeline settings and dedicated
viewers for segmentation tuning, reference masks, and ROI masks, while the CLI
supports scripted and repeatable runs. Both use the same settings models and
workflow engine.

## Install

FITS supports **Linux and Windows**. A **macOS installer is available for testing**;
Mac dependency compatibility and processing still need validation on real hardware.
An internet connection is needed to download Python and dependencies. No
separate Python installation or GPU is required: uv installs Python 3.12 and
creates a `.venv` inside the repository.

**uv is required and will be downloaded and installed automatically if missing.**
An existing uv installation is reused. uv is an independent third-party tool;
FITS does not maintain, update, or uninstall it. The installer uses uv's official
installer and installs it for your user in `~/.local/bin` (on Windows,
`%USERPROFILE%\.local\bin`), without changing shell profiles. No terminal restart
is needed for FITS installation or launch. To use a newly installed uv directly
in a terminal, add that directory to your PATH. Like the optional Tad viewer,
uv is maintained separately; unlike Tad, uv is mandatory.

### Linux

1. Install [Git](https://git-scm.com/downloads/linux).
   Open a terminal and check that Git is available:

   ```bash
   git --version
   ```

2. Clone FITS into a folder you can write to, then run the installer:

   ```bash
   git clone https://github.com/BennyGinger/FITS.git fits
   cd fits
   bash install_linux.sh --pause
   ```

   If you already cloned the repository, open a terminal in its main folder
   and run only `bash install_linux.sh --pause`. Use the terminal command;
   double-clicking a shell script may open it in a text editor.

3. Wait for the installation to finish. Answer the optional **Tad** viewer
   prompt, then press Enter to close. Open **FITS** from your Applications menu.
   You can also run `bash startup/launch_linux.sh` from the repository folder.

### Windows

1. Install [Git for Windows](https://git-scm.com/downloads/win).
   Open a new PowerShell window after installation and check Git:

   ```powershell
   git --version
   ```

2. Clone FITS into a folder you can write to:

   ```powershell
   git clone https://github.com/BennyGinger/FITS.git fits
   cd fits
   .\install_win.bat
   ```

   If you already cloned the repository, double-click **install_win.bat** in
   its main folder, or run `.\install_win.bat` from PowerShell in that folder.

3. Wait for the installation to finish. Answer the optional **Tad** viewer
   prompt, then press Enter to close. Open **FITS** from the Start menu or
   the desktop shortcut.

### macOS (experimental)

1. Install [Git](https://git-scm.com/downloads/mac), then open Terminal and check
   `git --version`. If macOS asks to install Command Line Tools, finish that first.

2. Clone FITS and run the Mac installer:

   ```bash
   git clone https://github.com/BennyGinger/FITS.git fits
   cd fits
   bash install_macos.sh --pause
   ```

   For an existing clone, run `bash install_macos.sh --pause` from its main folder.
   uv and Python are downloaded automatically when missing. Keep the terminal
   output and `startup/logs/install.log` if dependencies or verification fail.

3. After successful installation, double-click `FITS.command` in your home
   folder's `Applications` directory. It opens a terminal for startup and updates.
   Alternatively, run `bash startup/launch_macos.sh` from the repository folder.
   Install optional Tad separately from [its website](https://www.tadviewer.com/).

This installer uses the same dependency and import checks as Linux and Windows.
Apple Silicon/Intel compatibility and Apple GPU acceleration have not yet been
validated; providing this script does not guarantee every backend works on a Mac.

Run the FITS installers as your normal user, without `sudo` or **Run as
administrator**. Use a Git clone rather than a downloaded ZIP; the installer
fetches the required submodules automatically. Keep the repository folder
after installation, since the shortcuts launch FITS from there.

If installation fails, read the terminal message and
`startup/logs/install.log` (if created), fix the reported problem, and rerun
the same installer. See [installation details](#installation-details) for
optional settings, updates, and repair.

## Design

FITS owns experiment discovery, scheduling, state, paths, provenance, and saved
artifacts. Numerical work is delegated to focused submodules that accept arrays
and can also be used independently:

- `fits_io` reads microscopy formats and writes metadata-rich FITS TIFFs.
- `stackalign` performs time-wise and cross-channel registration.
- `bg_sub` removes spatially varying image background.
- `cellpose_kit` provides a stable Cellpose v3/v4 segmentation interface.
- `tracklink` links segmented objects over time.
- `mask_interpolation` completes sparsely drawn reference and ROI masks.
- `bioimagequant` performs object extraction and distance-profile analysis.
- `progress_bar` provides terminal progress and controlled log display.

`fits.pipeline` is the top-level processing entry point. Supporting workflow code
is grouped into definitions, experiments, metadata, artifacts, file management
and runtime execution. See the [workflow responsibility map](docs/workflow_architecture.md)
for module locations; `fits.workflows.file_management.api` exposes file actions
and compacting.

## Pipeline operation

`fits.pipeline.start_pipeline()` loads the TOML settings, discovers supported
raw images, restores saved experiment state, resolves overwrite decisions, and
runs enabled steps in this order:

```text
Convert → Preprocess → Process → Analysis
           |              |         |
           |              |         └─ distance profile, quantification
           |              └─ segmentation, tracking
           └─ channel registration, time registration, background subtraction
```

Every launch saves the input configuration, including its comments, as
`.fits/fits_settings.toml` in the run directory before processing starts. This also
applies when running `pipeline.py` with the packaged `user_settings.toml`,
so the GUI can later load the run's settings. The saved copy reflects the
latest launch and remains available if processing fails.

In the GUI, **Save settings** saves the current draft into the selected run without
starting processing. Changed snapshots are retained in `.fits/settings_history/`
before replacement. **Save protocol** exports a reusable TOML file, and **Load
protocol** validates it and asks before replacing the current GUI settings.
Both protocol actions require a selected run and are disabled during processing.
Protocols retain channel order, per-channel segmentation settings and custom model
paths, while preserving the current run directory, user name and log destination
on load. All protocol overwrite flags are reset to false. Loading does not save
the run settings or change results; use Save settings or Run to persist the draft.
When explicit channel labels do not match the source channel count, conversion
warns and falls back to `C_1`, `C_2`, etc. Empty labels also use reader defaults.
Named channel selections must match the resulting labels. Changed processing parameters flag
existing results and their dependents for the usual rebuild/continue decision.

Each series has an `experiment_state.json` file containing its artifacts,
completed steps, metadata, and provenance, stored inside its acquisition's
`.fits_experiment/experiment_state/<series>/` directory. Artifact paths, rather than a second
workflow manifest, are the durable evidence used to resume work. Conversion can
split a raw file into several experiment branches. Re-running an unchanged step
reuses completed output. FITS 4 keeps each preprocessing result independently:

| Step | Output |
| --- | --- |
| Convert | `fits_array_raw.tif` |
| Channel-shift | `fits_array_reg_channel.tif` |
| Frame-shift | `fits_array_reg.tif` |
| Background subtraction | `fits_array_bgsub.tif` |
| Segmentation | `fits_masks_seg.tif` |
| Tracking | `fits_masks_track.tif` |

Execution runs channel registration before time registration; the GUI tab order
is unchanged. Disabled preprocessing steps are bypassed even if their old files
remain. Overwriting reads the preceding enabled stage and preserves its pixels.
Each artifact records its own UTC `created_at` revision and the paths/revisions
of its actual inputs in `derived_from`; existing step timestamps keep their
previous meaning. Analysis Parquets carry the same provenance.

Before a GUI or CLI run, FITS compares recorded input revisions with current
files and propagates conflicts downstream. The shared dialog lists affected
files and offers **selected step and downstream**, **selected step only**, or
**cancel** for an overwrite. Selecting only that step suppresses dependent work
for this launch. A later launch warns about remaining conflicts and offers
rebuilding, continuing with existing results, or cancelling. These checks use
embedded revisions, not filesystem modification times. Plain Python callers
can pass `artifact_decision(report)` to `start_pipeline`; without a callback,
a required decision raises `PreflightRequired` instead of opening Qt.

Use **Manage files… → Compact experiment…**, or `uv run fits compact /path/to/run`, to
preview the exact retained and removed files. Compacting keeps the furthest
image as `fits_array.tif` and the active final object mask as `fits_masks.tif`,
including edited/filtered tracking when active. Original acquisitions, REF/ROI,
measurements, settings and reports remain. Superseded intermediates and viewer
caches are removed only after publishing and verifying the retained files and
state; publication failures roll back. If conflicts exist, choose rebuilding
first, deliberately retaining the existing downstream results, or cancelling.
Accepted conflicts remain recorded alongside the original provenance.

Files from FITS versions before 4, or files lacking revision provenance, remain
viewable but read-only until explicitly migrated through **Manage files**.
Migration updates folder structure, metadata, paths, identifiers and condition
tags without rerunning processing or changing pixels/measurements. It retains
the original producer metadata and records that historical lineage is unavailable.
A saved final image becomes an accepted checkpoint: an experiment stopped after
background subtraction can proceed to segmentation without recreating earlier
intermediates. Migration itself remains metadata/layout-only by default. Its
optional **Rebuild all experiment results** choice reruns the complete workflow
from original acquisitions, including final images, masks and measurements.
**This can take a long time, and final results may change**, even with the same
settings. Existing experiment results and state are backed up before processing
starts; their original scientific files are retained in that backup. Compacted experiments require rebuilding missing inputs when needed
for an upstream processing change.
REF/ROI drawings keep their pixels; compatible metadata can be refreshed without
redrawing. Changed registration revisions require reviewing their geometry.
Intensity-only changes do not invalidate their geometry. The full-rebuild policy is documented in [the rebuild plan](docs/full_rebuild_plan.md).
The earlier implementation plan is [the five-phase plan](docs/fits4_artifacts_plan.md).

### Portable acquisitions and Manage files

Conversion groups the original file and all its series into one portable folder:

```text
run/
  .fits/                         # settings, logs and reports
  control/image/
    image.nd2                    # original acquisition
    image_s1/                    # active scientific outputs
    image_s2/
    .fits_experiment/
      experiment_state/image_s1/experiment_state.json
      tuning/image_s1/
      cache/image_s1/
      backup/image_s1/<revision>/
```

The metadata directory is hidden on Linux and marked hidden on Windows. Moving
the complete acquisition carries its original, outputs, state, cache and history.
Selecting a processed series or acquisition in the GUI opens its containing run
automatically. FITS recognizes run roots by `.fits/fits_settings.toml` or
`.fits/logs/`; a detached processed folder needs its containing run restored.
The current run root takes precedence over a saved absolute `run_dir`.

The browser status panel shows a coloured compatibility summary, followed by
image channels and the total run-directory size, including retained backups. **Details…**, beside **Manage files…**, opens a scrollable
explanation with read-only/upgrade guidance and retained-history size. Compatible
experiment folders appear green; outdated folders and their parents appear orange
with warning icons. If any active experiment has older metadata or layout, the
**Upgrade to FITS v4 required - read-only**. Viewers and settings remain available.
In read-only runs, **Back** and **Next** let you inspect both Convert and
processing settings; **Next** never starts conversion in this mode.
**Manage files…** groups current-file actions separately from **Manage backups**.
Current-file actions check the whole run and use three controls:

- **Rebuild** changes its name with the required work: **Rebuild all results…**
  for migrated or compacted experiments, **Rebuild outdated results…** for stale
  downstream outputs, or **Rebuild required results…** for a mixture. Current
  experiments remain untouched. Complete reconstruction reruns final outputs as
  well as intermediates; it can take a long time and may change results. A backup
  is retained first. The button is disabled when no rebuilding is needed.
  For pre-v4 runs this control initially reads **Migrate to FITS 4…**, with an
  optional full rebuild, unchecked by default. Migrated arrays receive their
  actual stage filename; canonical `fits_array.tif` is reserved for compaction.
- **Update paths and condition tags…** is enabled only when saved state/settings
  references or existing master-table identities/tags differ from the current
  run. Condition tags belong to the master tables. Portable per-experiment
  Parquets remain unchanged during a location-only update. Without a master and
  with coherent saved paths, there is nothing to update. Location differences
  appear as orange warnings in the main status, browser and Details.
- **Compact experiment…**, slightly separated, removes intermediate files and
  caches while keeping essential files. It creates no persistent backup.

In Manage files, run guidance appears on the left and file-action buttons on the
right. Actions that do not apply are greyed out; their tooltips explain why.
Other GUI windows retain their existing button behavior.
Conflict, migration, rebuild and compaction reviews share one schematic for the
whole run. Each icon represents a workflow stage and shows its file count and
actions. Originals have no filename in the diagram. Teal means all files are
kept, purple marks outputs to overwrite/rebuild, orange marks affected or changed
files, and blue dashed icons mark new files. Shared renames show the old name struck through, a downward arrow and the
new name, even when other files already have the target name.
Click a stage to list its actual files and individual actions, grouped by
acquisition and series. The list scrolls for larger runs; clicking the diagram
background clears it. Review windows open larger and retain readable icons.
Use scrolling, zoom or Fit to inspect the complete sequence. Arrows distinguish
workflow order from recorded provenance and REF/ROI geometry relationships.
Path/tag-only updates list the affected files and explain each change.
Migration summarizes those updates above its schematic, with the full plan under
collapsed **Details**. Its optional full numerical rebuild checkbox switches
between the move/rename overview and complete reconstruction. Switching the
preview does not change any files.
**Manage backups** shows availability, saved versions and their total size, with
**Restore selected backup…** and **Delete selected backups…** actions.
The same manager is available with `uv run fits manage /path/to/run`.
The checker also runs when the GUI loads a run, showing orange folder/status
warnings and Details only when attention is needed. It runs again immediately
before GUI/CLI processing, where the shared rebuild/continue/cancel choices apply.
Checks do not claim to verify missing historical lineage of migrated outputs.

After moving an acquisition or changing condition folders, use **Update paths
and condition tags…**. Like the other two actions, it checks the entire run regardless of the
browser selection. It updates known paths,
identifiers and tags in existing per-series Parquets and regenerates master
tables, preserving measurement values and data revision timestamps. A numerical
rebuild reruns affected measurements instead. Folder names outside the acquisition
wrapper supply condition tags; see [analysis identifiers](docs/analysis_identifiers.md).

Retained backups are never deleted automatically by compaction. A storage hint
appears only when backups exist; delete reviewed snapshots through Manage
files to reclaim that space. Before migration or path/tag updates, FITS retains a complete original
run folder under `.fits/backup/<revision>/run/`, including original files,
metadata, settings and tables. This copy uses additional disk space; FITS checks
free space before migration and stops if the backup and working files will not fit. Restoring a
**Whole run** backup restores the original folder structure and file contents,
and retains the current run as another backup. Rebuilding existing results retains a per-experiment backup under
`.fits_experiment/backup/<series>/<revision>/`. A full rebuild replaces final
results as well as intermediates; it does not keep an old final image active
beside a new upstream chain. Per-experiment backups restore coherent outputs
and state. REF/ROI drawings are preserved;
if registration changes, inspect their alignment in the viewer before explicitly
accepting it through Manage files or recreating the drawings.

After a full run, the main GUI and interactive CLI show the same completion
dialog with the outcome and **Full report…**. Intentional drawing skips do not
turn successful runs into failures. Successful runs that can be compacted also
offer **Manage files…** with a space-saving hint. Convert → Next and nested
maintenance processing do not show a duplicate full-run completion dialog.

Runtime Advanced settings reserve their expansion space to keep the file browser
usable. Advanced sections in step tabs still expand and collapse normally.
GUI and CLI pipelines check free disk space before processing and before pending
steps. File-management actions use the same checker. Processing estimates use
the raw FITS array or current final array size multiplied by the number of outputs
to build, with additional headroom. If space is insufficient, the action stops
and explains how much space is needed and available. Retained-history deletion
remains available to reclaim space.
Implementation phases and validation are recorded in the
[portable experiments plan](docs/portable_experiments_plan.md).
The revised migration/processing boundary and module API are documented in the
[file management actions plan](docs/file_management_actions_plan.md).


The default conveyor execution lets prepared experiments advance while other
experiments are still upstream. In the interactive conveyor, reference/ROI
drawing can overlap with processing, while analysis waits for both its processed
image and finalized mask outcome. A failure is recorded for its experiment and
other experiments continue when possible. Preprocessing or processing failure
skips that experiment's downstream work; a user choosing to omit an optional
analysis input can produce a partial result. If every experiment fails, the
pipeline stops with an error.

Interactive-mask and conversion-only GUI runs write a timestamped log and full
text report under `.fits/logs/` and `.fits/reports/`, respectively. Reports list
completed, partial, skipped, and failed work by phase and experiment. The GUI
opens the latest report when a run
finishes; **Full Report** and report files in the directory browser can reopen
it later.

Quantification includes portable experiment paths and cell identifiers for
grouping measurements across intensity channels and time. See
[analysis identifiers](docs/analysis_identifiers.md) for their format, segmentation
behavior, and the deferred handling of independent Z planes.

Quantification can optionally measure cell compartments. Enable **Measure cell
compartments**, choose **Membrane thickness (pixels)** and optionally **Cell
expansion (pixels)**. Expansion preserves neighbouring labels without overlap
and defines the full-cell region before centroid measurement. Each cell is then
processed separately using a cropped distance transform, including where cells
touch. The `compartment` column contains `full`, `mb` and `cyto`; when disabled,
it contains only `full`. All compartments retain the parent cell identity,
full-cell centroid and reference distances. A fully eroded cytoplasm retains
one cell pixel nearest the full-cell centroid, excluded from the membrane.
Compartment masks are generated in memory during extraction. Enable **Save
compartment masks** to export `_mb.tif` and `_cyto.tif` beside the selected
segmentation/tracking mask using the FITS TIFF protocol. The source mask is
unchanged, including when dilation is enabled. Compaction removes these exports
while retaining source masks, measurements and settings. Rebuilding regenerates
them only when compartment measurement and saving remain enabled. Rerun extraction with overwrite to update existing
measurements.

The corresponding `[extract.params]` settings are `compartments = false`,
`membrane_thickness = 6.0` (finite and positive), `dilation_radius = 0.0`
(finite and non-negative), and `save_compartment_masks = false`. Both distances
are in pixels.

## Installation details

After FITS installs, the terminal offers to install **Tad**, an optional,
independently maintained third-party Parquet table viewer. Existing discoverable
installations are reused. FITS does not manage Tad updates. A Tad installation
failure does not prevent FITS installation or operation; the final message
confirms that FITS is ready. Use `--with-tad` or `--without-tad` to choose without
the prompt (noninteractive installations skip Tad by default). Automatic FITS
updates skip this optional setup. Automatic Tad installation currently supports
x86-64 Linux and Windows, using the official Tad 0.14.0 distribution; its files
and bundled licence notices are retained under `startup/tools/Tad`. Install
elsewhere from [Tad's website](https://www.tadviewer.com/) if preferred.
Double-click a Parquet file in the FITS run browser to open it in Tad. If Tad is
unavailable, FITS shows its installation link and suggests VS Code Data Wrangler
as an alternative. This does not affect pipeline execution.

The installer initializes the recorded submodules, runs ordinary `uv sync`,
checks GUI/backend imports and model-cache write access, and creates a per-user
Applications-menu entry on Linux, Start-menu and desktop shortcuts on Windows,
or a `~/Applications/FITS.command` launcher on macOS. It does
not run the pipeline or request model weights. Model downloads happen on first
use. GPU availability is reported without making it an installation requirement.
Run as your normal user, rather than as administrator or with `sudo`.

On Windows, installation also marks dot-prefixed files and folders directly
inside the checkout (including `.git` and `.venv`) as hidden. `uv.lock` and
`pyproject.toml` remain visible; installation clears their Hidden attribute if
an earlier installer hid them. FITS marks its
`.fits` metadata folders as hidden when creating or accessing them, keeping
their logs and caches out of ordinary Explorer views. Existing folders are
handled when next used; no drive-wide scan is performed. Hidden items remain
accessible through Explorer's **Hidden items** option. Failure to set the
attribute does not stop installation or processing. Linux behavior is unchanged.

Progress and subprocess errors are saved to `startup/logs/install.log`. If a
step fails, correct the reported problem and rerun the installer. Submodules
with local edits or commits differing from FITS's recorded versions cause the
installer to stop before changing their checkouts. No pull, reset, cleanup, or
automatic dependency upgrade is performed. If `uv sync` changes the lockfile,
the installer reports it for review.

Use `bash install_linux.sh --no-shortcut`, `bash install_macos.sh --no-shortcut`,
or `install_win.bat --no-shortcut`
to omit shortcuts. If an existing FITS shortcut points to another checkout,
the installer asks before replacing it, after the new installation passes its
checks. The old folder is left untouched. Rerunning in the same location
refreshes that user's shortcut. Separate OS users should use their own writable
checkouts and environments.

Deleting a development checkout removes its code and `.venv`; save local work
and data first, including changes inside submodules. Per-user model/uv caches
and the shortcut remain. A fresh clone and installation recreate the environment
and can repoint the shortcut. If moving a checkout, recreate its `.venv` at the
new location and rerun the installer; virtual environments are not portable.

### Startup updates and repair

Menu/desktop shortcuts and the launchers check FITS's configured upstream
`main`/`master` branch on startup. Every new FITS commit counts as an update;
tags/releases are not required. The check fetches only FITS, without checking
submodule remotes or changing the working checkout. If an update is available,
choose **Update FITS** or **Use current version**. Closing the prompt also keeps
the current version. If the network check fails, a working installation opens
with its current version; the failed check is recorded in the update log.

Updates require a clean checkout and a fast-forward from the installed commit.
Local edits, untracked files, conflicting module commits, or divergent history
disable automatic updating. FITS never stashes, resets, deletes local work, or
advances modules independently of their recorded commits. Developer branches
and checkouts without a configured main/master upstream skip automatic checks.

The prompt closes before installation starts. An independent process then
updates FITS to the selected commit, initializes/synchronizes the pinned
submodules, runs the installer checks, and refreshes this checkout's existing
shortcuts. Progress appears in a terminal window (Linux requires an installed
GNOME Terminal, Konsole, or xterm when launching from a desktop shortcut).
The GUI opens only after verification succeeds. Installing an update can take
time when dependency downloads are needed.

The supervisor/updater use uv's managed Python outside `.venv`, so they remain
available if FITS's environment needs repair. The installed Python path is saved
under `startup/logs/`; no extra virtual environment is created. A missing
environment, changed dependency receipt, or interrupted update offers **Repair
and launch**. If Qt itself cannot import, Windows's native dialog or Linux's
`zenity` provides a fallback; console launch remains available for repair.

An interrupted update retains its selected commit and can be retried. There is
no automatic rollback: one checkout and one `.venv` are updated in place. If a
step fails, inspect `startup/logs/update.log` and `install.log`; application
output is captured in `launcher.log`. The progress terminal offers retry after
fixing the reported issue. Local edits made during an interrupted update still
require manual reconciliation; they are never discarded automatically.

One supervised FITS session per checkout is allowed. Close FITS completely
before updating; the updater also checks the application lease used by direct
`uv run fits-gui` launches. Independent viewer commands should be closed too.

For troubleshooting, append `--skip-update-check` to a launcher to skip the
network check, `--repair` to offer synchronization, or `--check-only` to print
the available update as JSON without opening the GUI. Direct `uv run fits-gui`
continues to launch without the startup update check.

After first pulling the updater changes, rerun the OS installer once. This
records the independent Python path and refreshes shortcuts to use `startup/`.

Manual launchers live together in `startup/`:

- Linux: `startup/launch_linux.sh`.
- macOS: `startup/launch_macos.sh` (experimental).
- Windows: `startup/launch_win.vbs` opens without a console;
  `startup/launch_win.bat` keeps a console available for troubleshooting.

These enter the independent startup supervisor, which opens the GUI in the
checkout's `.venv`. After updating from the old root-level launchers, refresh
shortcuts by rerunning the OS installer.

### Manual development setup

Clone the repository together with its submodules, then synchronize the uv
workspace:

```bash
git clone --recurse-submodules https://github.com/BennyGinger/FITS.git fits
cd fits
uv sync
```

### Default GPU setup

Plain `uv sync` and `uv run` select the development defaults automatically:

- Windows x64 is configured for PyTorch 2.8.0+cu129 and torchvision
  0.23.0+cu129 from the CUDA 12.9 package index.
- Linux constrains PyTorch to 2.10.0 and torchvision to 0.25.0 and uses its
  existing package source. The Windows accelerator group does not apply there.

These describe the current dependency configuration, not a hardware validation.
Check GPU availability on the machine where FITS will run.

No extra flags are needed for everyday development:

```bash
uv run fits-gui
uv run fits-segtune
uv run cellpose
```

The shared default is `[tool.uv].default-groups = ["dev", "cuda129"]` in
`pyproject.toml`. To omit the Windows accelerator group:

```bash
uv sync --no-group cuda129
uv run --no-group cuda129 fits-gui
```

A later plain `uv sync` or `uv run` restores the shared default. The former
`cpu`, `cuda126`, and `cuda128` groups are not defined in the current project.
Omitting `cuda129` removes that group selection; it does not select a dedicated
CPU profile.

Check GPU availability from the FITS directory:

```bash
uv run python -c "import torch; from cellpose import core; print(torch.__version__, torch.version.cuda); print('Cellpose GPU:', core.use_gpu())"
```

Restart running Python sessions after changing PyTorch, and enable `use GPU`
in the Cellpose GUI (or pass `--use_gpu` to the Cellpose CLI).

Launch the main settings interface with `uv run fits-gui`, or open the image
tools directly:

```bash
uv run fits-segtune
uv run fits-drawmask
uv run fits-regtune
uv run fits-trackviewer --experiments-dir /path/to/run
uv run fits-trackedit /path/to/experiment/fits_masks_track.tif
uv run fits-channel-labels /path/to/run
```

In the main GUI, **Edit Channel Labels** sits between **Image / Mask Viewer** and
**Full Report**. It inspects every FITS artifact in the run directory, then
lets you rename labels by original source channel index. It maps channel
references in FITS TIFFs, measurement Parquets, experiment states, and saved
run settings, then writes only files that reference a changed label while
preserving image pixels and ImageJ overlays. A conflicting index-to-label
mapping stops the rename and names the affected files. The button is disabled
while the pipeline runs. The command line can inspect or preview the same run:

```bash
uv run fits channel-labels /path/to/run
uv run fits channel-labels /path/to/run --set 0=Green --set 1=Red
uv run fits channel-labels /path/to/run --set 0=Green --set 1=Red --apply
```

On Ubuntu, install an Applications-menu launcher with the FITS logo:

```bash
.venv/bin/python startup/shortcuts.py
```

Search for **FITS** in Applications, then pin it to your favourites if desired.
The launcher checks for updates before opening this checkout's GUI. Ordinary
launches do not open a terminal; accepted updates/repairs show terminal progress.
Rerun the installer if you move the repository.

In `fits-gui`, each segmentation channel has its own settings section. New
sections start with an empty target channel; enter its name explicitly before
running segmentation. Use
**+** beside the target channel to add a section, or **−** to remove one.
Each channel can use a different model, diameter, denoising option, and nuclear
helper channel. Execution and overwrite controls apply to the whole step.

Select a run directory with Browse, enter a path and press Enter, or drag one
local folder onto the main window or Run directory field. Folder selection loads
that run's saved settings, or fresh template settings if none exist. Folder
changes are blocked while the pipeline runs.

The **Activity log** header always shows a step label, progress bar, and elapsed
time. Batch runs mirror the current step's terminal counter; conveyor runs show
**Pipeline steps**, using the terminal Pipeline counter, including totals added
by output branches.
Conversion-only runs show **Convert**. Interactive runs show overall configured
stage completion as **Pipeline steps**. The elapsed clock has no time-remaining
estimate and freezes when work finishes; the blue activity indicator runs while
the pipeline is active.

Click **Preview** in the segmentation settings to preview Cellpose with those settings.
SegTune and RegTune open the experiment selected in the main GUI, or the first
available image when the run folder or no experiment is selected. For current
experiments, tuners resolve the preceding enabled stage through StepProfile.
The opened file is highlighted in the tuner's browser. Choosing an experiments
directory in a standalone tuner also opens its first available image.
SegTune combines **Segmentation** and **Compartment** tabs, styled like the
main workflow's step tabs, with blue/green backgrounds and titles above the
image. Segmentation Preview opens the Segmentation tab; Quantification's
Compartments Preview opens Compartment. The segmentation tab loads the saved
segmentation mask. Compartment loads the active tracking result (including
accepted edits/filtering), otherwise segmentation. A source indicator identifies
the saved mask or temporary segmentation preview. If no suitable mask exists,
an initial segmentation preview is generated.

Both tabs have **Run preview**, **Save current settings**, and a red **Close**
button. Run preview generates/reuses segmentation using its current settings;
Compartment then displays membrane rings. These previews never overwrite saved
source masks. Membrane thickness reuses cached distance maps; dilation or a new
mask revision rebuilds the geometry. Changed segmentation settings mark a
previous result as out of date until previewed again.

Segmentation retains a selectable channel-settings list. **Add channel**, beside
its heading, creates an entry for the next unused image channel. Each row's bin
removes that entry from both the tuner and main GUI without applying unrelated
pending edits; the last entry cannot be removed. **Save current settings** saves
all segmentation channel entries and keeps the window open. Compartment's
**Mask channels** list selects the mask geometry without add/remove controls.
The image-channel selector independently changes the fluorescence background:
for example, red-derived masks can be inspected over the green image channel.
Thickness and dilation are shared across mask channels. Saving the Compartment
tab copies only its options into Quantification.

Each tab remembers its display colour: **Palette**, a preset solid colour, or
**Custom…**. Opacity and visibility remain adjustable. Colours affect display
only, without changing labels or processing settings. Closing warns about
unsaved processing settings in either tab. Already saved settings and immediate
channel deletions remain applied. In the main GUI, use Save settings or Run
pipeline to persist the updated settings. Standalone saves update the run's
normal settings file; `fits-segtune [image-or-folder] --tab compartment` selects
the Compartment tab directly.

When segmentation is needed, the selected Cellpose model initializes in the
background. Changing model or denoising options queues the latest model for
initialization. Initialized models remain cached in the Python process, so
switching back reuses them; retaining several models uses additional CPU/GPU
memory.

Click **Preview** in the background-subtraction settings
section to open BGTune. It loads the GUI's current settings and selected
experiment, with run-directory browsing locked. Standalone `fits-bgtune` keeps
browsing and accepts an initial experiment/image, `--experiments-dir`, and
`--settings`, for example:

```bash
uv run fits-bgtune /path/to/experiment --settings /path/to/fits_settings.toml
```

The two actions sit to the right of the LUT: orange **Run preview** and dark
green **Save and close**. Run preview computes only the selected frame, channel
and Z plane in a worker. Navigating afterward computes only requested planes;
no neighboring frames or full stacks are prepared in the background. SMO's
configured processor is reused across same-sized planes with the same sigma
and window size. Window size must be at least 2 pixels (usually 3 or larger);
the SMO probability threshold is between 0 and 1. Visited results use an 8-plane/64 MiB cache (one oversized
current plane can remain displayable). Changing settings requires Run preview
again. Excluded channels pass through unchanged.

Choose **Original image** or **Background-subtracted image**, or press **V** to
switch rapidly with the same LUT and intensity limits. **Enable measurement
box** enables drawing, moving and resizing a rectangle. Its pinned results
show original and processed means and their difference, from the same raw pixel
coordinates. Measurements follow frame/channel/Z changes and ignore display
contrast. The rectangle only measures; processing always uses the full plane.
Background-subtracted arrays and preview caches retain signed `float32` values,
including negative and fractional residuals. Pipeline TIFF output also uses
`float32`; excluded channels keep their values in that dtype. Viewers show
negative pixels as zero in a separate display array. Box means and downstream
analysis use the signed values, not that display copy.

**Save and close** accepts settings even without a preview. It transfers them
to the main GUI without changing whether the background-subtraction step is
enabled. Advanced settings opens only when an advanced value, such as threshold
or statistic, changes; basic edits leave it collapsed. Standalone saving updates the supplied
or nearest general settings file, or creates one at the selected run root.
Images are never overwritten by the tuner; the measurement box and preview
pixels are not saved. The status bar reports each plane's processing time.
Press **R** to preview or **S** to save and close; **Info** lists the shortcuts.

Click **Preview** in the Frame-shift or Channel-shift settings to open
RegTune on its **Time registration** or **Channel registration** tab. Both tabs
share the same image browser and navigation. When launched from the main GUI,
its current settings take priority over saved experiment tuning. Explicit channel
changes in the top toolbar update the active tab's fitting/reference channel. **Run preview** fits the complete
time sequence or the channels at the selected reference frame in a background
worker; the button becomes **Cancel preview** while working. Z stacks use a
maximum projection for fitting, and the resulting 2D transforms apply to all Z
planes. OpenCV and pystackreg support translation, rigid-body, and affine;
scikit supports translation. Excluded channels stay unchanged and are not fitted.

Selecting a **Context** preset fills in its actual algorithm and method. They are
grouped under **Algorithm and method**, labelled **Set by context**. Editing either
selects the matching named context when one exists, otherwise **Custom** and
**Manual settings**. Returning to a preset's algorithm/method restores its context;
choosing a preset also restores its values. Custom is a viewer label only: saved settings
retain the last named context and explicit algorithm/method values.
Changing a registration context in the main settings panel also
updates its algorithm and method.

Registration TOML settings use `algorithm` for the implementation choice
(`scikit`, `pystackreg`, or `cv2`). Older `backend` keys are accepted when loading
settings and renamed to `algorithm` when saved.

Both tabs use three separate panels in the SegTune style: **Registration settings**,
**Fitting crop**, and **Resolved registration**. The first retains the registration
fields and algorithm/method group. Registration and crop settings scroll, while
the resolved panel stays fixed at the bottom of each tab. It shows the effective plan, for
example `pystackreg / translation / previous / full image` or `... / from crop`.
Channel registration shows its reference channel and frame instead of a time
reference strategy. The summary follows settings and enabled crop changes.

When SegTune or RegTune is opened from the main GUI, its run-directory field and
Browse button are disabled. Experiments within that run remain selectable.
Standalone tuners retain directory browsing.

Each tab has a **Fitting crop** subpanel explaining that a smaller region can
focus on stable features when full-image fitting is difficult and speed up
live-preview fitting, while registration still applies to the full
image with unchanged output size. Its **Enable crop** toggle is off by default. Enable it to draw, move
or resize a fitting rectangle; **Preview** zooms to the rectangle so you can
check it while navigating frames. There is no automatic Crop action. Disabling
the tool hides the rectangle, returns to the full view and uses the full image
for fitting, even if a rectangle remains stored. The crop limits fitting only:
transforms are converted to full-image coordinates and never trim the output.

After fitting, both tabs apply transforms only to the frame, channel and Z plane
being displayed. Visited registered planes are cached, up to eight planes or
64 MiB per preview. Moving to another frame does not repeat fitting. Channel
fitting uses only its reference frame; full-stack application happens in the
pipeline, rather than delaying the interactive preview.

Choose Original image, Registered image, or Composite overlay. The overlay
compares the original and registered images at the same frame, channel and Z
plane. The original is grayscale and the registered image uses the selected
channel LUT. When the registered image is grayscale, the original is magenta
instead. Both are auto-scaled separately and blended to show registration's
displacement. The canvas dimensions stay unchanged; transforms can leave empty
borders or move content outside the frame. Each tab previews its registration
directly on the source image; the Channel tab does not run time registration first.

**Save current settings** works with or without a preview. It updates the
general settings in the main GUI and saves the accepted experiment's settings,
crop and any matching fitted matrices in `<experiment>/.fits/registration/time.npz` or `channel.npz`.
Accepting changed manual algorithm/method overrides opens **Advanced settings**
in the main panel. Unchanged saves and named preset selections leave it
collapsed. All tuners preserve advanced sections the user already opened.
Save settings or Run pipeline in the main GUI persists the general settings,
as with SegTune. **Save current settings** saves only the selected tab and keeps
the viewer open for further time or channel tuning. **Complete session** saves
both tabs, then closes the tuner; a save failure keeps the viewer open.
Without a matching preview, saving stores settings and the fitting rectangle
without matrices, replacing any older accepted transforms. The pipeline fits
those settings later. Saving never applies the whole stack. Preview caches are released when
the experiment changes or the viewer closes; the source image is not modified.

Both pipeline registration tasks check accepted models before fitting. Tuned
experiments keep their accepted settings when general settings change. Matching
fitting pixels, channel labels, and image dimensions allow matrix reuse; changed
input triggers fresh fitting with the accepted settings. This also checks that
channel transforms tuned after time registration match the actual pipeline
input. Reuse avoids fitting, while resampling and saving images still run.
Delete the relevant tuning file to return an experiment to general settings.

Standalone launch supports an initial image/folder, tab, and settings file:

```bash
uv run fits-regtune /path/to/experiment --mode channel --settings /path/to/fits_settings.toml
```

Standalone Save updates the supplied settings file, or the nearest saved FITS
settings found within the browser root. Without one, it creates
`<browser-root>/.fits/fits_settings.toml` from the template. The module launcher
`python -m fits.gui.viewer.registration` accepts the same arguments.

The main interface has two pages. An unconverted run opens on **Convert**;
**Next** performs conversion only and moves to the processing page after it
finishes successfully. Reopening a run containing converted FITS images opens the
processing page directly, with **Preprocess** selected. **Back** returns to
Convert. An unchanged **Next** returns to processing without another conversion;
changed conversion settings, including overwrite, request a fresh conversion.

Conversion channel labels can be any names, but must follow the source image's
channel order. Raw ND2 and TIFF files can share a run, but must have the same
number of channels. Shared input checks run when the GUI loads a run directory
and before pipeline conversion; blocking problems appear in red in the GUI,
with affected files and corrective guidance in the warning and **Details**.
The channel-label input shows the expected raw channel count in italic.
A label-count mismatch shows a nonblocking orange warning, including the expected
count, entered count and complete list of fallback names. The GUI console shows
the warning in orange; correcting the labels clears the warning. Different raw
channel counts between experiments remain a red, blocking error.
Files with the same stem in the same folder receive extension-specific
acquisition folders (for example, `sample_nd2/sample.nd2` and
`sample_tif/sample.tif`), with a console log message and no popup. Original
filenames are preserved. Matching stems in different subfolders do not need
this adjustment. Existing or conflicting destination folders block conversion.
The GUI selects all channels for export by default; select a
subset to convert/export only those channels. Registration and segmentation
channel menus follow that export selection. Fitting and nuclear channels have
an optional **None** choice, while the required registration reference and
segmentation target start blank. Tracking offers only segmentation targets.
Multi-channel controls collapse to a one-line list of selected labels, with an
ellipsis when needed. Click to open the checked choices and toggle several
channels; click outside or press Escape to close. Hover shows the complete
selection alongside the parameter help. Exclusion controls keep **None**
exclusive of actual channel selections.

Tracking's optional **Enable mask repair** is for static or nearly static cells.
It builds a reference from consistently occupied pixels and rejects weak,
ambiguous, or unmatched observations before interpolating the resulting gaps.
**Minimum mask consistency** controls observed-mask Dice similarity and its
equivalent IoU for identity matching and reconstructed masks; the minimum IoU
is always at least 0.5. After collision clipping, a reconstructed mask must still
overlap its intended shape sufficiently. Tiny fragments do not count as completed
cells. Tracks that cannot be completed over the requested interval are removed.
Existing tracking files require rerunning Tracking with overwrite to apply these
rules; downstream measurements must then be regenerated.

Segmentation's main settings use the installed Cellpose built-in model list,
matching SegTune. FITS opens before loading Cellpose; model choices are discovered
once in a background thread while other settings remain editable. Saved model
selections stay visible; empty model controls show **Loading models…** until
discovery finishes. An early segmentation **Preview** request waits for that
same task, and Preview reuses its cached model choices and imported backend.
This discovery does not load model weights or change CLI pipeline behavior.
Diameter is entered as an integer. Flow threshold is a
nonnegative squared-error cutoff: values above 1 are meaningful, and 0 disables
flow-error filtering. Native 3D segmentation ignores this filter.
Settings changed while conversion is running apply to the next conversion.

The processing page has **Preprocess**, **Process**, and **Analysis** tabs,
each with smaller step subtabs across the top. **Frame-shift** and
**Channel-shift** are the time and channel registration settings. There is no
separate pipeline-step panel. Each step's **Enable** checkbox includes or omits
that step; its settings sit inside the Enable group. **Advanced settings** and
advanced runtime settings collapse fully, letting the tab's scroll area adjust
instead of reserving empty space.

**Run pipeline** launches the normal pipeline with the configured enabled steps
and overwrite rules, including Convert when enabled. The page layout does not
change the workflow's execution order or processing algorithms.

For enabled steps, the GUI requires conversion channel labels, a channel-
registration reference channel, at least one segmentation channel, and at
least one tracking channel. If one is missing, the GUI keeps the affected step
or phase selected and explains which field must be completed. **Run pipeline**
remains disabled until all required fields belonging to enabled steps have a
value. **Next** checks the Convert inputs independently of later steps, so
unfinished processing settings do not prevent conversion. These checks detect
omitted input only; the pipeline continues to handle
invalid channel names and other data-dependent validation.

Enable **Edit tracking** in the Process phase to review each active tracking
artifact after automatic tracking and before analysis. FITS opens the full
tracking editor with the experiment's configured input image; the displayed image
channel can be changed independently from the mask channel and is the channel
used by local mask prediction. **Save edited tracking** writes
`fits_track_edited.tif`, or `fits_track_edited_filtered.tif` when track-length
filtering is enabled, and makes that copy the experiment's active tracking
artifact. The original `fits_masks_track.tif` remains in place. **Use original
tracking** completes the optional step without replacing it. Quantification
then consumes only the active tracking artifact. Enable overwrite to reopen a
previously completed edit.

Standalone `fits-trackedit /path/to/experiment/fits_array_raw.tif` starts an empty
tracking session without an existing tracking mask. Add/Edit uses headless
micro-SAM with positive/negative prompts and an expected cell diameter defining
the local crop. Predict, inspect or brush-correct the proposal, then accept it;
accepted masks determine the centroids used for trajectories. Manual brush and
enclosed-fill operations remain separate from inference, as does the Split
predictor. The editor supports track merge/link, stopping or unlinking a track,
mask/track deletion, and undo. Saves use the edited-tracking filenames above
and record compact edit provenance. Redo, a replayable per-edit log, and the
static-only temporal policy remain pending; see the
[tracking TODOs](docs/todos.txt) and [micro-SAM cleanup plan](docs/microsam_tracking_cleanup.md).

`fits-drawmask` opens a dedicated mask editor with **Reference** and **ROI**
tabs sharing the same experiment and image controls. `fits-segtune` opens its
combined segmentation/compartment window. **Save current settings** keeps the
tuner open and updates the main GUI, or the run settings file when launched
standalone. **Close** leaves pending edits unsaved and asks before discarding them.
Opening an image also loads the first reference and ROI masks beside it, in
filename order. Selecting a mask file opens its sibling image and that specific
mask in the matching tab.
The former `fits-viewer` command has been removed.

**Image / Mask Viewer** loads current intermediates, canonical compacted images
and masks, supported older FITS files, and REF/ROI masks. Trajectories and track-length
filtering appear for tracked masks. Segmentation and branch masks offer image/mask
display without tracking-only tools. Earlier-version files cannot be edited.
The existing `fits-trackviewer` command also opens these supported files.

Segmentation tuning, Reference/ROI, and tracking viewers read image and mask
planes on demand through `fits_io`, as does registration tuning. Each plane cache holds at most eight planes
and 64 MiB. Edited mask planes are stored separately in a private temporary
directory and remain available when you move between frames. Save writes the
usual mask artifacts; closing the session removes its temporary edits. Tracking
saves assemble a disk-backed array plane by plane.
Reference/ROI live propagation previews prepare one selected-channel T or Z
sequence in a background thread and cache its completed mask states in a private
temporary directory under the experiment's `.fits/viewer_cache/`. Navigating
within that sequence reads cached planes without repeating interpolation.
The current plane and nearby planes are prepared first; moving the slider
reprioritizes remaining work. Ready planes are immediately usable, while a
missing preview has a translucent, fading loading overlay and a status/progress
indicator. Edits, undo, channel/depth changes, and propagation settings select
or invalidate the corresponding preview; stale background results are discarded.
Each drawing session retains one completed sequence. Temporary previews are
removed when replaced or the viewer closes, and read-only experiments fall back
to the system temporary directory. Source masks and ROI threshold/manual states
are preserved. Preview caches are session-local and do not reload unsaved work
on a later launch.
Saving with propagation reuses a matching cached sequence, calculating only
uncached sequences. ROI caches retain threshold and manual-edit states as well
as the information needed for display. Saving copies cached sequences directly to output storage and uses faster
lossless zlib compression (level 1), trading slightly larger files for speed.
Unsaved-work bookkeeping checks and copies only edited planes. Merging existing mask channels
and segmentation volume previews use their existing stack/volume routines.
Completing an unchanged drawing session checks channel revisions instead of
reading and comparing the full mask stacks.
Reference/ROI drawing offers **Brush** strokes and **Freehand polygon** fills.
Shift-click selects the connected mask region under the cursor; drag it to move
it, or use Shift-drag directly. Movement stays within the image and supports
Ctrl+Z. ROI movement retains local threshold states through manual overrides.
**Clear current** clears the displayed plane; **Clear all** clears every T/Z
plane of the selected mask channel in the session. Existing saved masks stay
unchanged unless you explicitly save a replacement. Clearing records empty
planes without reading or rewriting their pixels; reference Undo retains the
previous plane through storage references. Tracking deletion likewise defers
label removal until display/save and updates cached centroids directly.
Brush sizes up to 1001 pixels are available in REF/ROI and tracking.
Both settings panels keep
Undo, Clear current, and Clear all together in an untitled section below the
title and description, with Ctrl+Z, Ctrl+D,
and Ctrl+Shift+D shortcuts respectively. Every viewer Info button shows the
shared searchable shortcut table, filtered to the current viewer, with function
and mode/condition columns. GUI applicability stays hidden. Both tracking modes
have a Selection panel above Display settings, with the selected IDs, Clear
selection, and cell-ID entry. The viewer accepts comma-separated IDs and an
unlimited number of selected cells; Ctrl+click and text entry stay synchronised.
The tracking editor keeps its single-ID input and maximum of two selected tracks.
Press Enter or Select to apply IDs; unavailable or filtered-out IDs leave the
current selection unchanged. In the tracking viewer, Ctrl+left-click toggles a
cell, while Ctrl+left-drag selects all current-frame centroids inside a
temporary rectangle. In the editor, Ctrl+left-click selects a cell and
Ctrl+left-drag pans. Ctrl+scroll zooms in both.
To inspect the complete shortcut catalog, including its GUI applicability, run
`.venv/bin/python -m fits.gui.viewer.common.inspect_shortcuts` from the repository.
Info dialogs size their wrapped columns and rows to the current screen. REF/ROI
save preparation and tracking preparation/saving use the same white loading
overlay, with a status message; it clears on completion or failure.

Tracking centroids and trajectory drawings are prepared in the background, with
progress and the current stage shown at the bottom right. Frame navigation reuses
already-drawn, native-resolution trajectory overlays for every frame. These
are prepared once in disk-backed storage, so forward navigation and arbitrary
frame jumps need no trajectory redraw. Both the tracking viewer and editor keep
completed drawings in `.fits/viewer_cache/tracking_paths/` and load them on
reopening, without scanning mask pixels or drawing the paths again. Cache keys
include the source file stamp, channel/Z, actual centroid coordinates (including
filters and unsaved edits), and drawing style. Changed inputs therefore get a
new drawing; cancelled or incomplete drawings are never reused. Selection IDs
and white highlights use cached coordinates in a separate lightweight layer
and do not rebuild the base drawing.

In the read-only tracking viewer, **Save current display** writes a new
`fits_track_overlay[_filtered][_label].tif`: all channels, Z planes, and frames
from the associated image artifact, with their original pixel values, plus an embedded ImageJ
overlay. The current mask channel, Z plane, filtering, path/ID selection,
colours, and mask opacity determine the annotations across time. Annotations
appear over any raw channel at the selected Z plane. The source files remain
untouched; the raw image is required even when its display is switched off.
This export is uncompressed because ImageJ's native compressed-stack opener
can omit embedded overlays, so it may be considerably larger than the source.
Open it in ImageJ/Fiji with **File → Open** and toggle annotations with
**Image → Overlay → Hide Overlay / Show Overlay**. **To ROI Manager** exposes
the separately named masks, paths, centroid markers, and IDs. Save as TIFF to
retain the overlay.

The viewer's **Crop** panel sits below Track filtering. Turn on **Enable crop**
and click **Crop** to fit a rectangle around every selected cell's complete
masks across the recording, with 5% padding on each side. Fitting runs in the
background. You can also draw a rectangle with a left drag, with or without
Ctrl; cells whose current-frame centroids are inside it become selected. The
rectangle stays until you change or disable crop mode. Drag inside it to move
it, or drag an edge/corner to resize it. Clicking Crop again fits the rectangle
around the selected cells across time. Width and Height are
editable pixel dimensions. Manual rectangles and adjustments receive no added
padding. The rectangle colour is only a display aid.
**Preview** zooms to the rectangle; unchecking Preview or pressing Home shows
the full image. **Save current display** uses the current rectangle whenever
crop mode is enabled, in either view, and adds `_cropped` to the filename.
Turning crop mode off saves the full image. All raw channels, frames, and Z
planes use the same XY crop, with the embedded overlay clipped and shifted to
match. `fits_io` preserves metadata/calibration and records the source shape,
pixel bounds, and offsets in `spatial_crops` metadata.

The viewer's cached trajectory overlays use four bytes per pixel per frame and are mapped from disk;
they are not loaded into RAM in full. The persistent cache retains up to four
recent drawings within 2 GiB, always keeping the latest complete drawing even
when that drawing alone exceeds the limit. Older drawings are removed as needed.
Read-only experiments use temporary drawings instead. The first preparation,
changed settings, and drawings evicted from the cache still require work;
reopening a matching cached drawing only loads metadata and maps its pixels.
Edits and undo invalidate only affected centroid frames. Compressed
`.fits/viewer_cache/<mask filename>.centroids-c*-z*.npz` files inside each
experiment store centroid tables and all track lengths. They load automatically;
changed source files invalidate them. Valid older hidden caches beside masks
migrate to this folder on use. On read-only folders the viewer keeps its
in-memory cache if it cannot write the persistent cache.
Length filters use inclusive first-to-last frame spans, including gaps, matching
quantification's `track_length`. Filter results reuse the cached lengths rather
than rescanning observations. Recent trajectory drawings are reused for filters
selecting the same tracks with the same style. This in-memory drawing lookup
retains at most four entries and 2 GiB; a drawing larger than this limit remains
usable as the active display but is not retained in the in-memory lookup for later
reuse; its completed disk cache remains available. New filter results prepare
their first drawing in the background. Edits clear stale drawings, and closing
or switching experiments releases the in-memory lookup. Filter controls remain
editable and only apply when **Filter** is pressed; **Clear filter** restores
all tracks without resetting the entered values.
Viewers initially select the image channel matching the first loaded mask channel.

To open the collection panel in preview mode without running the pipeline:

```bash
uv run fits-drawmask --tool pipeline
```

Click **Load test experiments…** and choose a folder containing prepared
FITS image artifacts. The panel starts in Reference mode. **Go to ROI** /
**Go to ref** switches between Reference and ROI; unsaved changes require confirmation before
being discarded. New experiments join the waiting list without replacing the
current drawing. **Complete ref masks** or **Complete ROI masks** finalizes that
mask type and moves to the other one; completing the second type finishes the
experiment. **Next experiment** finishes the current experiment after any
needed warnings, and remains unavailable until the next queued experiment is
ready. **Complete session** ends collection normally; **Quit pipeline** is a
separate cancellation action. Buttons explain their actions when hovered.
Unsaved-change baselines retain lightweight plane references rather than copying
both mask stacks when opening or switching experiments. Only edited planes need
pixel comparisons, and saved channels update their references without stack copies.

The experiment tree shows all received experiments, highlights the current one,
and lists saved masks underneath each folder. Click a current experiment's mask
to reload it for editing. Masks from other experiments open for viewing only;
**Return to current experiment** restores your ongoing drawing. Newly saved
masks appear in the tree immediately.

**Load test experiments…** is only present in this preview. In the integrated
window, the pipeline supplies prepared experiments automatically; there is no
manual folder loader.

This is a preview with no running pipeline, but **Save writes real mask files**
to the selected experiment folders. The regular `fits-drawmask` command keeps
the standalone browser and visible tabs.

You can also supply `--experiments-dir /path/to/run` and
`--settings /path/to/fits_settings.toml`. Without a settings file, the preview
requests one reference per experiment and no ROI. With settings, it uses the
enabled extraction/distance-profile steps and their drawing options.

To run the connected drawing workflow with slow demonstration steps:

```bash
uv run fits-gui --demo-step-delay 5
```

Choose your run folder and settings in the main GUI, enable **Distance profile**
(or **Quantification → Draw reference masks**), then click **Run pipeline**.
The drawing window opens automatically once the first image is prepared.
Preparation continues for the other experiments, so the queue grows while you
draw. Completing an experiment's masks releases its analysis. Missing
references omit distance profiling for that experiment; no ROI means
whole-image profiling after confirmation.

The delay is five seconds between steps, including between arrivals when images
are already prepared. Ordinary `uv run fits-gui` has no artificial delay.
Interactive runs currently use one preparation worker and one downstream worker;
existing noninteractive batch/conveyor execution remains available. **Quit
pipeline** stops new work and waits for any already-running step to finish.
The drawing requests and early-finish choices are currently run-local; reopening
a run reuses saved masks and asks for finalization again.

The command-line interface is available through `uv run fits --help`. Running
`uv run fits run path/to/settings.toml` launches the same Ref/ROI collection
window when the configured analyses request interactive masks. Calling
`start_pipeline()` directly stays noninteractive unless a mask interaction
bridge is supplied.

Runtime `log_dir` overrides the root for FITS metadata. FITS creates
`.fits/logs/` and `.fits/reports/` below that root; when `log_dir` is empty,
both are created below `run_dir`.

## Repository maintenance

FITS uses Git submodules and a uv workspace. The practical commands for
cloning, updating, editing, adding, and removing submodules are collected in
the [Git and submodule cheatsheet](docs/git_cheatsheet.md).
