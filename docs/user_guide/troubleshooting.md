# Troubleshooting

[User guide](README.md) ·
[Previous: Reprocessing and file management](reprocessing_and_file_management.md)

Start with the exact error and the latest report. Record the FIScH version, operating system, action you attempted, and relevant settings. Installation errors and processing errors have different logs and recovery steps.

## Find the right first check

| Symptom | First check / next action |
| --- | --- |
| Installation does not finish | Read `startup/logs/install.log` and [installation details](installation.md#installation-details); correct the reported issue and rerun setup. |
| Update or startup repair fails | Read [Startup updates and repair](installation.md#startup-updates-and-repair) and its update/launcher logs. |
| Channel choices are missing or names become generic | Check source count/order and exported channels in [Channels and labels](channels_and_labels.md). |
| Next or Run pipeline is disabled | Complete the required fields of the enabled step; see [processing settings](runs_and_settings.md#processing-tabs-and-required-settings). |
| Results look outdated or a run is read-only | Open Manage files and review [reprocessing/file management](reprocessing_and_file_management.md). |
| A moved folder is reported as detached | Check that the [portable project](portable_projects.md) includes its containing run and metadata. |
| Segmentation/tracking quality is poor | Inspect the [segmentation preview](segmentation.md) and [tracking results](tracking.md) before rerunning downstream analysis. |
| GPU/model loading or memory problems occur | Keep the exact error; compare model/processing settings and the [GPU configuration](../dev/development_setup.md#default-gpu-setup). Model downloads can require internet access. |
| Measurements are missing or repeated | Check [table row meanings and missing values](output_tables.md), the inputs, and enabled analyses. |
| Insufficient disk space | Read the required/available sizes and review retained backups before retrying. |

## Completion reports and free-space checks

After a full run, the main GUI and interactive CLI show the same completion
dialog with the outcome and **Full report…**. Intentional drawing skips do not
turn successful runs into failures. Successful runs that can be compacted also
offer **Manage files…** with a space-saving hint. Convert → Next and nested
maintenance processing do not show a duplicate full-run completion dialog.

GUI and CLI pipelines check free disk space before processing and before pending
steps. File-management actions use the same checker. Processing estimates use
the raw FIScH array or current final array size multiplied by the number of outputs
to build, with additional headroom. If space is insufficient, the action stops
and explains how much space is needed and available. Retained-history deletion
remains available to reclaim space.

## Processing logs and reports

Interactive-mask and conversion-only GUI runs write a timestamped log and full
text report under `.pipeline/logs/` and `.pipeline/reports/`, respectively. Reports list
completed, partial, skipped, and failed work by phase and experiment. The GUI
opens the latest report when a run
finishes; **Full Report** and report files in the directory browser can reopen
it later.

## Custom log locations

Runtime `log_dir` overrides the root for FIScH metadata. FIScH creates
`.pipeline/logs/` and `.pipeline/reports/` below that root; when `log_dir` is empty,
both are created below `run_dir`.

## Report a reproducible problem

Include the FIScH version, platform, exact message, relevant log/report, and the smallest settings/example that reproduces the issue. State which steps completed before the failure and whether the run was migrated, moved, compacted, or edited.

Display contrast does not change stored measurements. A skipped step may be intentional; read its reported reason. Reaggregating tables cannot detect unmeasured mask edits, so rerun the affected analysis when numerical inputs change.
