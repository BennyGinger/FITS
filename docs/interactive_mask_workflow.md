# Interactive Mask Collection and Pipeline Orchestration

## Status and purpose

This document records the design discussed in September 2026 and the first
working implementation. Sections labelled as future work remain proposals;
the implementation status and checklist near the end distinguish completed
work from follow-up work.

The goal is to connect FITS's viewers to the main workflow so that users can
create reference and ROI/inclusion masks while independent pipeline work
continues. This workflow is connected to `fits-gui` and to the CLI pipeline
entry points. The reusable `start_pipeline()` API remains noninteractive unless
it is given a mask-interaction bridge. Processing errors retain the existing
fail-fast behavior.

The design distinguishes three user experiences:

- A conversion/preparation lock is a possible later GUI safeguard; it is not
  part of the current implementation.
- Segmentation viewing is an optional tuning tool launched from segmentation
  settings.
- Reference and ROI viewers are interactive pipeline activities launched only
  when enabled analyses need user-created inputs.

## Current architecture

At the time of writing:

- `FitsMainWindow` presents every workflow step in one settings tree and runs
  the complete pipeline through a single `PipelineWorker`.
- While that worker runs, most main-window controls are disabled.
- `fits-segtune` opens `SegmentationTunerWindow` for segmentation tuning.
- `fits-drawmask` opens `MaskDrawingWindow` with Reference and ROI tabs.
  Both windows share image display/navigation components and independently
  discover materialized `fits_array.tif` files. The combined `fits-viewer`
  command has been retired; mask drawing creates no segmentation session.
- `ExperimentState` persists produced artifacts and completed steps.
- Every registered step has one declared `input_artifact` and one
  `output_artifact`.
- Batch execution runs each enabled step over all experiment states before
  moving to the next step.
- Conveyor execution advances experiments independently, but still follows a
  linear list of enabled steps.
- Missing artifacts are generally detected inside task implementations and
  raised as `StepExecutionError`; the scheduler does not model interactive
  waiting.
- Conversion, registration, and background subtraction update the image
  artifact and use `fits_array.tif` as their materialized output name.

The last point is important: a viewer must not draw masks against an image that
will subsequently be geometrically transformed. Mask collection can begin only
when the image has reached the final coordinate system used by analysis.

## Intended user flow

### Proposed GUI conversion lock

In a future version, if the selected run contains no usable `fits_array.tif`,
processing controls could remain visible but unavailable. The GUI would explain
that conversion is required and offer a **Convert images** action.

That action is only a GUI convenience. It invokes the existing pipeline with a
runtime-effective configuration in which conversion is enabled and all other
steps are disabled. It should not overwrite the user's saved enabled/disabled
choices.

The lock is based on actual usable image artifacts, not only on whether
`convert` appears in `completed_steps`. Previously converted experiments must
unlock the interface when a run directory is reopened. If some experiments
convert successfully and others do not, valid experiments can become
available while failures remain visible.

The CLI does not require this artificial conversion boundary. It may continue
to execute the configured workflow directly from raw inputs.

### Segmentation tuning

Segmentation settings provide an **Open segmentation tuning** action. The
viewer loads available experiments and initializes itself from the current
segmentation settings. Applying settings sends validated values back to the
shared settings model/editor.

Opening this viewer is optional. It does not become a prerequisite for running
segmentation, and the user is not expected to tune every experiment manually.

### Interactive analysis inputs

When an enabled analysis requests reference or ROI masks, FITS examines each
applicable experiment after its image is safe to view. Existing valid masks are
reused. Missing masks become interactive requests shown in a persistent **Mask
Collection** window.

The manager resolves one experiment at a time. Once an experiment becomes
safe to view, its reference- and ROI-mask work is presented as one collection
session. Other ready experiments wait in the experiment queue; the user does
not move between partially resolved experiments. The current experiment is
released only after every required mask type has been explicitly finalized.
Finalization may mean that the requested masks were saved, or that the user
confirmed that some or all remaining slots should be skipped.

The initial number of requests comes from settings, but it is a target rather
than a rigid declaration of every final artifact. During execution, the user
can:

- save masks and assign their labels;
- change the expected reference and ROI counts with minus/plus controls;
- finish a mask type early and skip its remaining slots;
- switch explicitly between reference and ROI tools;
- reload and edit masks already saved on disk;
- cancel the entire pipeline.

Analysis starts only after the user explicitly finalizes the relevant mask
collection. Merely reaching the initial target count does not release analysis,
because the user may still add another mask.

Mask requirements are analysis-specific. Extraction may use reference masks
but does not use ROI masks. Distance profiling requires at least one finalized
reference mask; without one, it is omitted for that experiment. ROI masks only
restrict which pixels contribute to a distance profile and are optional. When
none are supplied, distance profiling proceeds over the whole image.

After finalization, that experiment can continue towards analysis while the
manager opens the next queued experiment. This experiment-at-a-time UI does
not introduce a global pipeline barrier: preparation and computational work
for other experiments may continue in the background.

## Pipeline phases

The interactive coordinator should reason about phases rather than acquire a
new boolean for every workflow step:

```text
Phase 1: image preparation
    convert → register_time → register_channel → bg_sub

Phase 2a: computational processing
    segment → track

Phase 2b: user input collection
    reference masks and ROI masks

Phase 3: analysis
    distance_profile → extract
```

Phase 2a and Phase 2b can proceed in parallel:

```text
                               ┌─ segmentation → tracking ───────┐
prepared experiment ───────────┤                                 ├─ analysis
                               └─ interactive mask collection ───┘
```

These assignments are the initial proposal, not a reason to hard-code step
names throughout the GUI. A later step should be assignable to a phase without
adding another field to an experiment progress object.

The durable `ExperimentState` continues to record individual artifacts and
completed steps for provenance and restart behavior. The interactive
coordinator derives phase readiness from the enabled steps and their outcomes.

Phase 2 has two visible branches, so progress should retain the distinction:

```text
Processing:  queued / running / completed
User input:  not needed / waiting / finalized / skipped
```

## Readiness and concurrency

Conveyor execution is the natural mode for an interactive run. As soon as one
experiment finishes Phase 1, FITS can do both of the following without waiting
for the remaining experiments:

1. submit its Phase 2a computational work; and
2. append its missing masks to the growing interactive queue.

Phase 3 should use a per-experiment join rather than a global barrier:

```python
analysis_ready = (
    image_preparation_complete(experiment)
    and computational_inputs_ready(experiment, analysis)
    and user_inputs_finalized(experiment, analysis)
)
```

Consequently, Experiment A can enter analysis while Experiment B is still
being prepared or while the user is drawing Experiment B's masks.

Batch mode remains useful for noninteractive CLI runs, tests, and simple
workflows, but is clunky for this interaction because it naturally creates
global barriers. An initial implementation may use those barriers to reduce
complexity, but the target interactive behavior is conveyor-based.

### Safe point for opening a viewer

“As soon as possible” means as soon as the displayed image is in the final
coordinate system used by the downstream analysis. In particular, opening a
viewer immediately after conversion is unsafe when a later registration step
will transform the image.

The initial conservative rule can be to wait until all enabled Phase 1 steps
for that experiment are complete. The prepared `fits_array.tif` must then be
treated as immutable while the viewer, segmentation, and analysis read it.

## Mask requirements and runtime manifest

The settings and integrated collection panel are implemented. Each analysis
specifies its drawing requests:

```toml
[extract.params]
draw_ref_mask = false
expected_ref_masks = 1

[distance_profile.params]
draw_ref_mask = true # Fixed true; no reference toggle in the GUI.
expected_ref_masks = 1
draw_roi_mask = false
expected_roi_masks = 1
```

The optional drawing toggles request user input; they do not disable automatic
use of existing mask artifacts. Extraction does not request ROIs. Reference
counts are at least one; ROI counts may be zero. The distance-profile manager
rejects experiments without any reference artifacts, independently of these
request counts. It does not require an ROI or an exact match to a target.
The numerical packages receive their existing numerical arguments only.

Names should make the intent explicit in the GUI, for example **Initial
reference masks to request**. Counts initiate work; they do not identify
artifacts and do not necessarily determine the final number saved.

As the user works, FITS builds a runtime manifest:

```text
Experiment A
├── Reference masks
│   ├── nucleus        saved
│   ├── membrane       saved
│   └── requested #3   skipped
└── ROI masks
    ├── whole_cell     saved
    └── requested #2   queued
```

The label entered by the user when saving becomes the stable identity of an
artifact. A saved requirement is uniquely identified by at least:

```text
experiment + mask kind + label
```

Applicable channels may also need to be part of the identity or metadata. Two
enabled analyses requesting the same artifact must produce only one drawing
request.

Requested slots without labels are queue placeholders. Compact minus/plus
buttons change the expected count for each mask kind. A required reference
cannot be reduced below one, and a count cannot be reduced below the number
already saved. Finishing with unmet targets records the remaining requests as
skipped internally; the skipped count is not shown in the interface.

The manifest is authoritative for the masks used by that execution. Before an
analysis starts, it takes a finalized snapshot of the applicable manifest.
Adding masks after analysis has started should initially be disabled; supporting
that later would require invalidating or rerunning affected analysis work.

Reference and ROI finalization have different downstream consequences:

- finalizing with no usable reference blocks only analyses that require a
  reference for that experiment;
- finalizing with no ROI does not block distance profiling and explicitly means
  that the whole image is included; and
- enabling extraction alone must not create an ROI request because extraction
  does not consume ROI masks.

Whether this runtime manifest needs its own durable file, or can initially be
reconstructed from saved mask artifacts plus run-local decisions, remains an
open design question.

## Mask request lifecycle

Waiting state is needed only for user-generated inputs in the first version.
Normal computational dependencies continue to rely on canonical pipeline
order.

A mask request has a small run-local lifecycle:

```text
missing artifact discovered
          ↓
        QUEUED
          ↓
        ACTIVE
          ↓
     SAVED or SKIPPED
```

`missing` need not be stored; it is the condition that creates a request.
Pipeline cancellation is a run outcome rather than another mask status.
Completed requests may be removed from active queues while their outcomes are
retained for the final report.

Skipping a mask must not mark an analysis step as completed. It blocks or skips
only the analysis branches that actually require that mask. Independent
experiments and analyses continue.

The general fail-fast behavior for genuine processing exceptions can remain in
place initially. User skip and user cancellation are control outcomes, not
processing exceptions.

## Mask Collection window

### Implemented panel preview

`fits-drawmask --tool pipeline` opens `MaskCollectionWindow`. The standalone
command still opens the ordinary browser editor. Both reuse `MaskDrawingWindow`
and the image controls; the collection subclass supplies a control panel in
place of the source browser. This avoids copying the drawing implementation.
A separate embeddable editor widget can be extracted when embedding is needed.

The preview accepts experiment folders through **Load test experiments…** or
`--experiments-dir`, and optionally reads request counts from `--settings`.
It does not start a pipeline. Saving still writes actual mask artifacts.

The GUI entry point is `enqueue_experiment(MaskCollectionRequest(...))`.
Requests append to the waiting queue; duplicate image paths are ignored.
Each new active experiment starts in Reference mode. Hidden tab shortcuts cannot
bypass the switching buttons and their unsaved-change warning.
`no_more_requests()` distinguishes a temporarily empty queue from completed input.
These slots run on the GUI thread; PipelineWorker signals deliver requests
from the preparation worker without touching widgets there.

The window emits `experiment_finalized(MaskCollectionOutcome)`,
`collection_finished()`, and `cancellation_requested()`. Outcomes contain saved
artifact paths and skipped counts.

### First connected pipeline version

`fits-gui` now connects this window through `PipelineWorker` signals and the
Qt-free `MaskInteraction` queue/events. When distance profiling is enabled, or
extraction requests reference drawing, `start_pipeline` selects the interactive
coordinator in `fits/workflows/interactive.py`.

One preparation worker runs conversion, registration and background subtraction
for each experiment. Only then does it emit a drawing request. It continues
preparing the next experiment while the main coordinator runs segmentation and
tracking and waits for per-experiment mask outcomes. Each finalized experiment
can enter analysis independently; the coordinator validates its final mask files
before analysis reads them. Missing references omit distance profiling, while
extraction can continue. No ROI is a permitted whole-image outcome.

This is a small initial conveyor with a single preparation worker and serial
downstream scheduling. It does not yet use the ordinary conveyor's full CPU/GPU
pool scheduling or every experiment-level worker setting. Noninteractive runs
retain their existing batch/conveyor paths. The CLI entry points create the Qt
event loop on the main thread and run the same interactive coordinator in a
worker thread.

`uv run fits-gui --demo-step-delay 5` adds cancellable five-second pauses after
steps. With pre-prepared inputs it also spaces drawing requests five seconds
apart. The default delay is zero and this flag does not alter saved settings.

Finishing drawing early resolves remaining and future requests using existing
artifacts and skips missing inputs without reopening the window. Quitting sets a
cancellation event, stops new work, and waits for already-running tasks to finish.
Cancellation is reported separately from errors. Preparation/task errors surface
through the GUI's existing failure dialog. Outcomes are not yet persisted as a
resume manifest; saved mask files remain the durable artifacts.

The collection panel shows a folder-style experiment tree containing every
received experiment, including the highlighted current one and completed ones.
Saved reference/ROI files appear as children and refresh after saving. Clicking
an active experiment's mask reloads it for editing, with the existing discard
warning if needed. Other experiments' masks can be inspected in the same image
area without advancing the queue or changing finalized artifacts. Their drawing
controls are disabled; **Return to current experiment** restores the active
image, navigation and unsaved canvas. Folder clicks do not change queue order.
All collection buttons have descriptive tooltips. The mode-finish and Next
buttons share a row. Finish drawing and the red Quit pipeline are stacked at
the right of the footer.
The manual folder loader is hidden whenever `preview=False`; the integrated
window receives its experiments only through coordinator requests.

### Current integrated layout

Reference and ROI tools remain scientifically distinct and live in one
persistent manager window with a shared experiment/image context.

The standalone `fits-drawmask` retains its directory browser and visible
Reference/ROI tabs. The integrated window replaces the directory browser with
the collection control panel and hides the tab bar. Drawing widgets are shared.

The implemented layout is:

```text
CONTROL PANEL                         IMAGE AREA
Experiment 2: condition/sample_04      Channel   mode   Overlay
5 experiments waiting                 Image viewer
Ref expected: 3 · 1 saved  [-] [+]    Frame / Z navigation
ROI expected: 1 · 0 saved  [-] [+]    LUT | Saving | session actions
Experiment folders and saved masks          Label [........] [Save mask]
[Finish reference masks] [Next experiment]  [Finish drawing]
[Go to ROI]                                [Quit pipeline — red]
Current mode's drawing controls...
```

One switch button always offers the other drawing mode. Switching is
user-controlled and is independent of expected counts. When the current mask
has unsaved changes, switching first warns:

```text
Save your work before switching, otherwise your unsaved changes will be lost.

[Cancel] [OK — discard changes and switch]
```

Cancel keeps the current drawing and mode. OK discards only the unsaved changes
for the mode being left and switches to the requested mode. The warning does
not implicitly save or delete a saved artifact. Saved masks remain available
for loading and editing. Clean switching does not show a warning.

Only the current mode's finish action is shown: **Finish reference masks** or
**Finish ROI masks**. **Finish drawing** ends the complete drawing session,
with confirmation of unsaved work and unresolved requests, and returns control
to the pipeline. It does not cancel the pipeline. Independent runnable analysis
continues; distance profiling still cannot run without a reference.
Only the explicit **Quit pipeline** action (or a confirmed stop after closing
the window) cancels the run. Its red styling distinguishes it from completion.

### Queue ordering

The manager keeps one experiment active at a time and shows the waiting queue.
Within that experiment, users may switch freely between reference and ROI
controls using the buttons. There is no forced reference-then-ROI sequence.
Experiment advancement remains separate from tool switching. Expected counts
are editable targets rather than an automatic finalization trigger. Finishing
early uses a warning; neither drawing mode is locked by counts. A temporarily
empty queue shows that preparation is still in progress when more experiments
are expected. When the final experiment is complete, **Next experiment** closes
the collection window normally. **Finish drawing** also closes without a warning
when all expected masks are saved; it warns about unfinished or unsaved work.

### Actions and their exact scopes

Button labels must state their scope. **Finish drawing** is reserved for ending
the complete collection session; mode-specific finish actions finalize only
references or ROIs for the active experiment.

- **Save mask** persists the current artifact under its entered label.
- **Minus/plus** changes the expected count for the corresponding mask kind
  without clearing drawings or deleting saved masks.
- **Next experiment** finalizes the experiment and closes the drawing window
  when the queue is complete.
- **Finish reference masks for _experiment_** finalizes that type for the
  experiment.
- **Finish ROI masks for _experiment_** does the equivalent for ROIs.
- **Finish drawing** ends collection after confirming unsaved work and remaining
  requests; it does not cancel the pipeline.
- **Quit pipeline** requests cancellation of the entire run.

If unfinished target slots remain, finalization asks for confirmation:

```text
You saved 1 of the 3 requested reference masks for sample_04.
Skip the remaining 2 and continue?

[Return to drawing] [Skip remaining and continue] [Quit pipeline]
```

When the user finalizes or skips ROI collection without saving an ROI, the
manager gives a separate confirmation:

```text
No ROI mask is selected for sample_04.
Distance profiling will include every pixel in the image.

[Draw an ROI mask] [Use the whole image] [Quit pipeline]
```

This confirmation is also shown when distance profiling is enabled but the
initial ROI target is zero, so whole-image analysis is an explicit decision.
It is not shown when no enabled analysis consumes ROI masks.

Closing the window is not equivalent to skipping. It warns that closing will
stop the pipeline and offers **Return to mask collection** or **Stop pipeline**.

### Existing artifacts and editing

The integrated control panel uses a flat experiment list rather than the
standalone directory browser. Experiment labels are paths relative to the run
directory, so condition folders remain visible without showing long absolute
paths. Each experiment expands only to its saved reference and ROI masks:

```text
condition/Experiment A
├── fits_ref_nucleus.tif
├── fits_ref_membrane.tif
└── fits_roi_whole_cell.tif
```

Selecting a saved mask loads its sibling image, switches to the correct viewer
mode, and loads the mask and its label. Masks from the active experiment open
for editing; masks from other experiments open read-only and can be left using
**Return to current experiment**. Saving an existing label updates that artifact
without increasing the saved count.

Labels must be unique within an experiment and mask kind. Attempting to reuse a
label should offer to update the existing mask, choose a different label, or
cancel. Rename and deletion semantics can be deferred, but must not silently
leave stale manifest entries.

Mask files should be saved atomically. The pipeline may attempt to read a mask
immediately after receiving the saved event, and it must never observe a
partially written artifact. A saved mask should also be validated against the
prepared image before its request is released.

## GUI and CLI execution model

Qt widgets and the Qt event loop must remain on the main thread. The pipeline
must not directly open or manipulate a viewer from an executor thread.

The intended arrangement is:

```text
Main thread
    Qt event loop
    Mask Collection window
    user interaction

Pipeline coordinator thread
    workflow scheduling
    phase/readiness decisions
    interactive request coordination

Existing executors
    CPU tasks
    GPU tasks
```

A separate subprocess is not required merely to keep the UI responsive. It
would add cancellation, serialization, exception-reporting, shared-state, and
GPU-ownership complexity. The existing executor strategy can remain behind a
coordinator running outside the Qt main thread.

Communication should use requests and outcomes, conceptually:

```text
coordinator -- mask_requested(request) --> Qt main thread
coordinator <-- mask_resolved(id, outcome) -- Mask Collection window
```

In `fits-gui`, this extends the current worker-thread arrangement. In an
interactive CLI run, the CLI creates the Qt application/event loop on the main
thread and runs pipeline coordination in a worker thread. A future resolver
interface should allow different policies:

- Qt interactive resolver;
- noninteractive resolver that skips missing masks;
- strict resolver that reports missing masks as an error.

This separation prevents Qt concepts from leaking into the workflow engine.
Interactive CLI behavior should ultimately be explicit through configuration
or a command-line option, especially for headless environments.

## Cancellation

When the user quits:

1. stop accepting new viewer requests;
2. stop scheduling new pipeline tasks;
3. cancel tasks that have not started;
4. cooperatively stop, or allow completion of, work already running;
5. close the viewer after the coordinator acknowledges cancellation; and
6. report the run as cancelled, including completed and skipped work.

Exact cancellation guarantees depend on the underlying processing libraries
and executor type. The UI must not claim that a running task was cancelled if
it was only prevented from scheduling downstream work.

## Implementation stages

The feature can be introduced without immediately redesigning all dependency
handling.

### Stage 1: GUI integration boundaries — partial

- Viewer content was split into shared base, segmentation and mask-drawing
  windows. `fits-segtune` and `fits-drawmask` remain standalone tools.
- Segmentation tuning launches from segmentation settings and applies results
  through `SettingsAdapter`.
- The GUI-only conversion lock remains future work.

### Stage 2: Interactive mask collection — implemented

- Introduce Qt-free mask request and outcome models. A durable runtime manifest
  remains future work.
- Build the persistent Mask Collection window and experiment/mask display.
- Generate initial request slots from settings.
- Support save, update, editable target counts, finalization, and quit semantics.
- Pause before analysis while mask collection is resolved.
- Keep current fail-fast handling for processing errors.

This stage established the interaction model used by the connected coordinator.

### Stage 3: Initial conveyor coordination — implemented

- Assign steps to phases in one central place.
- Detect the per-experiment Phase 1 boundary.
- Grow mask queues as individual experiments become safe to view.
- Run Phase 2a processing concurrently with Phase 2b interaction.
- Re-evaluate an experiment's analysis readiness after computational completion,
  mask save, mask skip, or mask-type finalization.
- Submit Phase 3 per experiment without a global barrier.

### Stage 4: CLI integration and reporting — partial

- The normal CLI entry points launch the Qt resolver when configured analyses
  request interactive masks.
- Explicit skip-missing and strict headless policies remain future work.
- Add a final report covering saved masks, skipped requests, analyses omitted
  because no usable masks were supplied, processing failures, and cancellation.
- Consider persisting the runtime manifest for robust resume behavior.

## Implementation checklist

This table is intentionally ordered so the first working draft can remain
sequential. Conveyor concurrency is added only after the same phase and mask
contracts work end to end. `[x]` means implemented, `[~]` means partially
implemented, and `[ ]` means future work.

| Status | Milestone | Completion check |
|---|---|---|
| [x] | Define phases and outcomes | The interactive coordinator separates preparation, computation, user input and analysis without duplicating artifact state. |
| [x] | Classify the current steps | Current steps have one central phase assignment. |
| [x] | Add mask request and outcome models | Requests, expected counts, saved paths and skipped counts are represented without Qt dependencies. |
| [x] | Refactor the viewers | Shared image/navigation code supports separate segmentation and mask-drawing windows. |
| [x] | Build the experiment-scoped Mask Collection manager | One experiment is active while the growing queue, saved masks, editable targets, finalization and cancellation remain visible. |
| [x] | Connect coordinator requests to the GUI | The coordinator exchanges requests/outcomes through signals and never manipulates Qt widgets. |
| [x] | Integrate reference masks | Existing references are reused and new references can be collected before dependent analysis. |
| [x] | Integrate ROI masks | Existing ROIs are reused, new ROIs can be collected, and no ROI means whole-image profiling. |
| [x] | Define analysis expansion | Distance profiling expands reference/ROI inputs; extraction uses references and never requests ROIs. |
| [x] | Add per-experiment release | Finalized experiments continue while the manager advances through the queue. |
| [~] | Add conveyor scheduling | The first version overlaps preparation, drawing and per-experiment downstream work with conservative serial scheduling. Full scheduler/pool integration remains. |
| [x] | Make conveyor the GUI default | Saved templates and the main GUI default to conveyor; batch remains available. |
| [ ] | Add the GUI preparation lock | Processing settings remain unavailable until usable prepared images exist; the user's saved settings are not overwritten. |
| [~] | Add CLI mask policies | Interactive CLI execution is connected; explicit noninteractive-skip and strict-missing-input modes remain. |
| [~] | Complete cancellation and reporting | GUI cancellation stops new scheduling and differs from failures; a complete final run report remains. |
| [~] | Verify the complete workflow | Focused unit, coordinator, headless Qt and GUI connection tests pass; CLI policies and durable restart outcomes remain. |

## Invariants to protect

The implementation should preserve these rules:

1. Never draw against an image that may still be geometrically transformed.
2. Once exposed to mask collection and downstream readers, the prepared image
   must not be overwritten.
3. Counts create initial work slots; labels identify saved artifacts.
4. Reaching a target count does not finalize collection; the user finalizes it
   explicitly.
5. Only one experiment is active in the Mask Collection manager; the next
   experiment opens only after the current experiment's required mask types are
   finalized.
6. Analysis reads a stable snapshot of a finalized mask manifest.
7. Updating an existing mask does not create another completed request.
8. Skipping a mask does not mark an analysis as completed.
9. A missing reference blocks only analyses that require it for that
   experiment; a missing ROI means whole-image distance profiling after clear
   user confirmation.
10. Missing user input blocks only work that actually depends on it.
11. Closing the viewer cannot silently convert unresolved work into skips.
12. Qt UI activity remains on the main thread.
13. Saved masks are validated and written atomically before dependent work is
    released.
14. The workflow engine deals in requests and outcomes, not Qt widgets.

## Open questions

These points should be resolved before or during implementation:

- Are channel selections part of the mask identity, mask metadata, or both?
- Apart from distance profiling, what is the precise minimum reference-mask set
  for each future analysis to remain runnable after the user finishes early?
- Should skipped target slots be persisted across resumed runs, or requested
  again next time?
- Where should the runtime manifest live, and how is it reconciled with files
  added, removed, or renamed outside FITS?
- Can finalized masks be edited before analysis begins? What should happen when
  editing is requested after analysis has begun or completed?
- What cancellation guarantees can each task/executor realistically provide?
- How should users select skip-missing or strict behavior when the CLI runs
  without a graphical display?

Distance-profile output uses long-form rows for every reference label/channel,
ROI label/channel, intensity channel, frame, and distance bin combination.
Each ROI is evaluated independently, and a second whole-image variant is
represented by missing ROI label/channel values. FITS normalizes mask identity
columns across analysis outputs as `ref_label_name`, `ref_channel`,
`roi_label_name`, and `roi_channel` where applicable.


## Current GUI details

Conveyor is the default execution mode. Advanced settings start collapsed while
retaining their layout space. The drawing panel gives more height to the experiment
list; experiment folders show paths relative to the run directory, with saved masks
as their children. Finish drawing closes without a warning when all expected masks
are saved and all requests have arrived. Finishing early still asks for confirmation.

The shared viewer footer reserves roughly half its width for the smaller LUT and
its vertically centred intensity buttons. In collection mode, the grey Saving
section sits between the LUT and the right-aligned Finish drawing/Quit pipeline
buttons. File label, its expanding text field and the conventional-width Save
mask button share one row. The current mode appears between Channel and Overlay
above the image, with spacing at the outer edges.

Compact minus/plus controls beside each expected count replace Skip/Add. They
change the count without clearing drawings or deleting files. Required reference
counts cannot drop below one, and counts cannot drop below the number already
saved. The skipped counter is hidden. A visible draggable divider resizes the
experiment display; the scrolling drawing-settings area grows or shrinks below
it. **Go to ROI/ref** sits below the Finish-mask/Next-experiment row.

In the ROI Threshold section, dragging the plotted range updates both the current
plane values and the Manual range values. Min, Max and **Apply to stack** share a
single row to keep the panel compact.
