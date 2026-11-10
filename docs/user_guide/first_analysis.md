# Your first analysis

[User guide](README.md) · [Previous: Installation](installation.md) ·
[Next: Runs, channels, and settings](runs_and_settings.md)

Use this route for a first pass through the GUI. A named example dataset, its expected results, and matching screenshots are still to be added; the steps below describe the general workflow.

## Before you start

Install and open FIScH, choose a small acquisition, and check its source channel order. Use a time series if you want to try tracking. Keep the FIScH version and settings with your results.

## Pipeline operation

FIScH loads your settings, discovers supported raw images, reuses saved
experiment state where possible, and runs enabled steps in this order:

```text
Convert → Preprocess → Process → Analysis
           |              |         |
           |              |         └─ distance profile, quantification
           |              └─ segmentation, tracking
           └─ channel registration, time registration, background subtraction
```

## Process a first acquisition

1. Choose your run folder and enter your user name. See [Runs and settings](runs_and_settings.md).
2. In **Convert**, supply [channel labels in source order](channels_and_labels.md), select exported channels, and click **Next**.
3. Inspect the converted image and enable only the [preprocessing](preprocessing.md) corrections needed.
4. Configure [segmentation](segmentation.md), preview representative frames, and save suitable settings.
5. Enable [tracking](tracking.md) for the segmented channels if needed.
6. Enable [quantification and/or distance profiling](analysis_and_results.md), then click **Run pipeline**. Complete [REF/ROI drawing](reference_and_roi_masks.md) when the enabled analysis requests it.
7. Read the completion report, inspect images/masks, and open a saved measurement table.

## Check the outcome

A successful conversion produces a portable acquisition folder with a FIScH raw image for each series. Later enabled stages add their outputs; see [saved filenames](runs_and_settings.md#experiment-state-and-saved-outputs). Use the [output-table reference](output_tables.md) to interpret measurements and [Troubleshooting](troubleshooting.md) if the report shows failed or skipped work.
