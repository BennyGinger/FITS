# FIScH user guide

Each main settings tab and preview/editor has its own page. Open a topic below,
or search from the GUI's **ⓘ → User guide** tab. Related pages are linked at the
top of each topic. Shortcut tables are available in **ⓘ → Shortcuts**.

## Start here

- [Install, launch, and update](installation.md)
- [Your first analysis](first_analysis.md): the workflow from source images to results.
- [Main GUI, runs, and settings](runs_and_settings.md): opening a run, navigation, saving, and execution.

## Main settings tabs

| Tab | Dedicated page | Interactive tool |
| --- | --- | --- |
| Convert | [Convert](settings/convert.md) | [Channel labels editor](tools/channel_labels.md) |
| Preprocess → Frame-shift | [Frame-shift](settings/time_registration.md) | [Time-registration preview](tools/time_registration.md) |
| Preprocess → Channel-shift | [Channel-shift](settings/channel_registration.md) | [Channel-registration preview](tools/channel_registration.md) |
| Preprocess → Background subtraction | [Background subtraction](settings/background_subtraction.md) | [Background preview](tools/background_subtraction.md) |
| Process → Segmentation | [Segmentation](settings/segmentation.md) | [Segmentation preview](tools/segmentation.md) |
| Process → Tracking | [Tracking](settings/tracking.md) | [Tracking editor](tools/tracking_editor.md) |
| Analysis → Quantification | [Quantification](settings/quantification.md) | [Compartment preview](tools/compartments.md) |
| Analysis → Distance profile | [Distance profile](settings/distance_profiles.md) | [Reference editor](tools/reference_masks.md) / [ROI editor](tools/roi_masks.md) |

[Shared processing settings](settings/common.md) explains Include, Overwrite,
Execution and Workers.

## Workflow overviews

- [Preprocessing](preprocessing.md): alignment and background correction.
- [Segmentation](segmentation.md): object masks and previews.
- [Tracking](tracking.md): automatic linking, inspection and correction.
- [Reference and ROI masks](reference_and_roi_masks.md): roles and drawing workflow.
- [Analysis and results](analysis_and_results.md): choosing analyses and reading results.

## Other GUI tools

- [All preview and editing tools](gui_tools.md)
- [Shared viewer controls](tools/viewer_controls.md)
- [File Viewer](tools/tracking_viewer.md): raw images, masks and tracked results.
- [Pipeline mask collection](tools/mask_collection.md)
- [Manage files](tools/manage_files.md), [channel labels](tools/channel_labels.md), and [backups](tools/backups.md)
- [Full Report](tools/full_report.md)

## Reference and troubleshooting

- [Channels and labels](channels_and_labels.md)
- [Image/mask viewer reference and ImageJ metadata](viewers.md)
- [Understanding the output tables](output_tables.md)
- [Analysis identifiers](analysis_identifiers.md)
- [Portable projects](portable_projects.md)
- [Reprocessing and file-management concepts](reprocessing_and_file_management.md)
- [Troubleshooting](troubleshooting.md)
- [Developer documentation](../dev/README.md)
