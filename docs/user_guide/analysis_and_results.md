# Analysis and results overview

[Guide home](README.md)

Related: [Workflow](first_analysis.md) · [Output tables](output_tables.md) · [Reference/ROI workflow](reference_and_roi_masks.md)

Choose the analysis matching the question you want to answer.

| Analysis tab | What it measures |
| --- | --- |
| [Quantification](settings/quantification.md) | Measurements for each object, optionally split into compartments. |
| [Distance profile](settings/distance_profiles.md) | Intensity in bins around references, optionally restricted by ROI masks. |

## Open the results

Run the enabled analyses and read the completion report. Each series saves its own `proc_quantification.parquet` and/or `proc_distance_profile.parquet`; the run folder contains the corresponding master tables. Double-click a Parquet in the run browser to open optional [Tad](installation.md#optional-tad-installation), or use the Data Wrangler alternative described there. Master tables combine rows rather than averaging cells. Use [Analysis identifiers](analysis_identifiers.md) to distinguish experiments and cells.

## When to rerun analysis

Excluding or re-including a converted series changes the membership of combined
analysis. The checker flags affected master tables as outdated. **Manage files →
Rebuild analysis…** combines valid results from active experiments again, without
rerunning valid measurements or deleting selected rows from an existing master.
Missing or outdated individual results require their processing rebuild first.
See [experiment exclusion](runs_and_settings.md#exclude-experiments-after-conversion).

After changing images, object masks, or references, rerun the affected analysis with overwrite. Updating software or aggregating old tables does not update their numerical measurements. Missing physical calibration leaves the corresponding physical-distance values empty; read the [output conventions](output_tables.md#units-missing-values-and-dimensions) before interpreting null or repeated values.
