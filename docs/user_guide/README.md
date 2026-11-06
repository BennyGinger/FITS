# FITS user guide

A practical guide to processing microscopy images with the FITS GUI, from
installation to inspecting measurements.

The chapters explain installation, processing, result interpretation, and file
management. Topic-specific details are integrated into each guide, with links
to shared explanations for channels, tables, viewers, and portable projects.
The first-analysis chapter provides a general route through the GUI; a named
worked dataset and screenshots are still to be added. The
[project README](../../README.md) provides the short overview and quick usage.

## Start here

1. [Install, launch, and update FITS](installation.md).
2. [Your first analysis](first_analysis.md): the general start-to-finish workflow.
3. [Runs, channels, and settings](runs_and_settings.md).

For channel naming, fallback names, and renaming existing results, see the
dedicated [Channels and labels](channels_and_labels.md) guide.

## Process your images

4. [Preprocessing](preprocessing.md): registration and background subtraction.
5. [Segmentation](segmentation.md): channels, models, and tuning.
6. [Tracking and corrections](tracking.md).
7. [Reference and ROI masks](reference_and_roi_masks.md).
8. [Analysis and results](analysis_and_results.md): quantification, compartments,
   distance profiles, and opening measurement tables.

## Maintain and troubleshoot a run

9. [Reprocessing and file management](reprocessing_and_file_management.md).
10. [Troubleshooting](troubleshooting.md).

## Detailed guides

- [Preview and editing GUIs](gui_tools.md): a separate feature list for each
  preview, REF/ROI drawing tool, and tracking viewer/editor.
- [Inspect artifact metadata in ImageJ/Fiji](viewers.md#inspecting-artifact-metadata-in-imagejfiji):
  open a TIFF's readable processing summary and understand its relationship to FITS metadata.
- [Moving a project: what is portable?](portable_projects.md): whole projects,
  acquisition folders, individual exports, and refreshing paths/condition tags.
- [Understanding the output tables](output_tables.md): all standard dataframe
  columns, units, optional measurements, examples, and grouping without double-counting.
- [Image and mask viewers](viewers.md): shared navigation, drawing tools,
  selection shortcuts, cropping, and exported overlays.
- [Analysis identifiers and measurement columns](analysis_identifiers.md): saved
  experiment/cell identifiers, compartments, track lengths, and motion measurements.
- [Developer documentation](../dev/README.md): architecture and implementation records.

