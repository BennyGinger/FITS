# User-guide screenshot plan

[Developer documentation](README.md) · [User guide](../user_guide/README.md)

Status: planned; screenshots have not been captured or added to the guide.

Aim for **six core figures**, with **two optional additions**. A comparison
figure can contain two small views where that makes the result easier to assess.
This is a capture checklist, not a requirement to illustrate every chapter.

## Core figures

| Done | Figure | What to capture | Main destination |
| --- | --- | --- | --- |
| [ ] | Main GUI overview | One annotated window identifying run selection, processing tabs, Preview, Run pipeline, status, and reports. Help users orient themselves once. | [Your first analysis](../user_guide/first_analysis.md) |
| [ ] | Segmentation preview | An image with its mask overlay and the relevant model/diameter controls. Show what a usable segmentation looks like. | [Segmentation](../user_guide/segmentation.md) |
| [ ] | Registration comparison | A composite overlay showing misalignment and the corrected result, ideally with a fitting crop. Show what to assess before accepting settings. | [Preprocessing](../user_guide/preprocessing.md) |
| [ ] | REF versus ROI | Two small views of the same image, showing a reference and an inclusion region. Make their different purposes clear. | [Reference and ROI masks](../user_guide/reference_and_roi_masks.md) |
| [ ] | Tracking correction | One before/after example of an incorrect assignment and its correction, with IDs visible. Demonstrate the result of editing. | [Tracking and corrections](../user_guide/tracking.md) |
| [ ] | Conflict-review diagram | A selected rerun, affected downstream outputs, and the separate REF/ROI branch. Explain the consequences of the selected action. | [Reprocessing and file management](../user_guide/reprocessing_and_file_management.md) |

## Optional figures

| Done | Figure | What to capture | Main destination |
| --- | --- | --- | --- |
| [ ] | Background subtraction | Original/corrected views using identical display limits, with measurement-box values. Distinguish numerical correction from display contrast. | [Preprocessing](../user_guide/preprocessing.md) |
| [ ] | Compartment preview | Clearly distinguished full-cell, membrane, and cytoplasm regions. Illustrate which pixels contribute to each measurement. | [Analysis and results](../user_guide/analysis_and_results.md) |

## Capture and presentation rules

- Use one representative acquisition throughout where practical.
- Crop out irrelevant controls while retaining enough context to locate the tool.
- Add only a few callouts, with short captions explaining the task or expected result.
- Use identical display limits when comparing image intensities.
- Put each figure in one main location; link to it from other chapters.
- Avoid separate captures for every operating system or every setting.
- Record the FIScH version and example settings used, so captures can be checked
  after GUI changes.

## Topics that do not need screenshots

Prefer the existing commands, example tables, folder tree, and short procedures
for installation, channel-count warnings, channel-renaming fields, output
tables, portable folders, and ImageJ metadata inspection. Add a screenshot only
if later user feedback identifies a specific ambiguity those explanations do
not resolve.
