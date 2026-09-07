# Interactive Mask Collection and Pipeline Orchestration

## Status and purpose

This document records a proposed design discussed in September 2026. It is a
planning document, not a description of functionality that is already
implemented.

The goal is to connect FITS's viewers to the main workflow so that users can
create reference and ROI/inclusion masks while independent pipeline work
continues. The same interactive workflow should be usable from `fits-gui` and
from an interactive CLI invocation. The design should require as little change
as practical to ordinary step execution and should initially preserve the
current fail-fast behavior for processing errors.

This proposal distinguishes three user experiences:

- Conversion is a GUI prerequisite that unlocks processing controls.
- Segmentation viewing is an optional tuning tool launched from segmentation
  settings.
- Reference and ROI viewers are interactive pipeline activities launched only
  when enabled analyses need user-created inputs.

## Current architecture relevant to this proposal

At the time of writing:

- `FitsMainWindow` presents every workflow step in one settings tree and runs
  the complete pipeline through a single `PipelineWorker`.
- While that worker runs, most main-window controls are disabled.
- `FitsViewerWindow` is a reusable `QMainWindow` that independently discovers
  materialized `fits_array.tif` files. It supports segmentation tuning,
  reference masks, and ROI masks.
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

### GUI conversion lock

If the selected run contains no usable `fits_array.tif`, processing controls
are visible but unavailable. The GUI explains that conversion is required and
offers a **Convert images** action.

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
- add more masks than initially requested;
- skip individual requested slots;
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

Settings specify an initial target such as:

```toml
reference_mask_count = 3
roi_mask_count = 2
```

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

Requested slots without labels are queue placeholders. **Add another mask**
adds a placeholder beyond the initial target. Skipping a placeholder records
that the user intentionally did not fill that portion of the target.

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

Reference and ROI tools should remain scientifically distinct, but live in one
persistent manager window with a shared experiment/image context.

A possible layout is:

```text
┌───────────────────────────────────────────────────────────────────┐
│ Mask Collection — Experiment 2 of 7: sample_04                    │
│                                                                   │
│ [Reference masks: 4 waiting]  [ROI masks: 3 waiting]             │
│                                                                   │
│ Reference — target 3, saved 1, skipped 0, remaining 2             │
│ Current task: Reference 2 of 3                                    │
│ Label: [ membrane ]                                               │
│                                                                   │
│                         IMAGE VIEWER                              │
│                                                                   │
│ [Skip this mask] [Add another mask]           [Save and next]     │
│ [Finish reference masks for sample_04]                            │
│                                                   [Quit pipeline] │
└───────────────────────────────────────────────────────────────────┘
```

The current mode must always be conspicuous: window title, section heading,
accent color, output filename, and instructions should all distinguish
REFERENCE from ROI. Viewer switching should be initiated by the user rather
than happen unexpectedly while a drawing is in progress.

The control panel also shows the experiment queue, for example **Experiment 2
of 7** and **5 experiments waiting**. It does not allow arbitrary navigation to
the next experiment while the current one is unresolved. **Next experiment**
becomes available only after all required mask types for the current experiment
have been finalized. If requested slots remain, moving on uses the same
explicit skip confirmation as finishing a mask type early.

### Queue ordering

The manager maintains a growing queue of experiments, with reference and ROI
requests grouped inside each experiment. It loads one experiment and processes:

```text
all references for that experiment → all ROIs for that experiment
```

This minimizes image reloads and keeps completion/finalization scoped to one
experiment. The reference-to-ROI mode transition must be explicit, and the
application must not switch modes while a drawing is active. When the
experiment queue is temporarily empty but more experiments are still being
prepared, the manager waits and reports that preparation is still in progress.

### Actions and their exact scopes

Button labels must state their scope. A generic **Finish** or **Skip drawing**
is too ambiguous.

- **Save mask** persists the current artifact under its entered label and marks
  the current slot complete.
- **Save and next** saves and activates the next suitable request.
- **Skip this mask** skips only the current placeholder.
- **Add another mask** adds a placeholder for the current experiment and mask
  type.
- **Finish reference masks for _experiment_** finalizes that type for the
  experiment.
- **Finish ROI masks for _experiment_** does the equivalent for ROIs.
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

Potential bulk-skip actions should also state their scope explicitly, for
example:

- Skip remaining reference masks for this experiment.
- Skip all remaining masks for this experiment.
- Skip all remaining reference-mask collection.

The first two are sufficient initially. Global skipping is powerful and should
not be easy to trigger accidentally.

Closing the window is not equivalent to skipping. It warns that closing will
stop the pipeline and offers **Return to mask collection** or **Stop pipeline**.

### Existing artifacts and editing

The directory browser should be reorganized around experiments and categorized
outputs:

```text
Experiment A
├── Source image
│   └── fits_array.tif
├── Reference masks
│   ├── fits_ref_nucleus.tif
│   └── fits_ref_membrane.tif
├── ROI masks
│   └── fits_roi_whole_cell.tif
├── Segmentation
│   └── fits_mask.tif
└── Tracking
    └── fits_track.tif
```

Selecting a saved mask loads its sibling image, switches to the correct viewer
mode, loads the mask and its label, and changes the action from **Save new
mask** to **Update mask**. Updating an existing mask must not increase the
saved count.

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

## Proposed implementation stages

The feature can be introduced without immediately redesigning all dependency
handling.

### Stage 1: GUI integration boundaries

- Add the GUI-only conversion lock and **Convert images** action.
- Unlock processing based on discovered usable image artifacts.
- Refactor viewer content into an embeddable widget if necessary, retaining a
  thin standalone `FitsViewerWindow` wrapper.
- Launch segmentation tuning from segmentation settings and apply results back
  through `SettingsAdapter`.

### Stage 2: Synchronous interactive mask collection

- Introduce mask requirement, request, outcome, and runtime-manifest models.
- Build the persistent Mask Collection window and categorized artifact browser.
- Generate initial request slots from settings.
- Support save, update, add, skip, finalization, and quit semantics.
- Pause before analysis while mask collection is resolved.
- Keep current fail-fast handling for processing errors.

This stage may use a phase barrier. It proves the interaction model without
requiring concurrent scheduling.

### Stage 3: Conveyor coordination

- Assign steps to phases in one central place.
- Detect the per-experiment Phase 1 boundary.
- Grow mask queues as individual experiments become safe to view.
- Run Phase 2a processing concurrently with Phase 2b interaction.
- Re-evaluate an experiment's analysis readiness after computational completion,
  mask save, mask skip, or mask-type finalization.
- Submit Phase 3 per experiment without a global barrier.

### Stage 4: CLI policies and reporting

- Add explicit interactive/noninteractive CLI behavior.
- Support the Qt resolver from interactive CLI execution.
- Add a final report covering saved masks, skipped requests, analyses omitted
  because no usable masks were supplied, processing failures, and cancellation.
- Consider persisting the runtime manifest for robust resume behavior.

## Implementation checklist

This table is intentionally ordered so the first working draft can remain
sequential. Conveyor concurrency is added only after the same phase and mask
contracts work end to end.

| Status | Milestone | Completion check |
|---|---|---|
| [ ] | Define phases and outcomes | Each experiment reports preparation, computation, user-input, and analysis status without duplicating `ExperimentState` artifact data. |
| [ ] | Classify the current steps | Existing steps run through the four logical parts using one central phase assignment. |
| [ ] | Implement a sequential coordinator | CLI and GUI can execute preparation, computation, mask resolution, and analysis sequentially. |
| [ ] | Add mask requirement and manifest models | Initial targets, saved labels, skipped slots, and per-type finalization are represented without Qt dependencies. |
| [ ] | Refactor the viewer for embedding | Existing drawing/viewing functionality remains reusable inside a manager while the standalone viewer stays thin. |
| [ ] | Build the experiment-scoped Mask Collection manager | Exactly one experiment is active; queued experiment count, reference/ROI controls, save, update, add, skip, finalize, and quit are available. |
| [ ] | Connect coordinator requests to the GUI | The coordinator emits mask requests and receives outcomes; it never opens or manipulates Qt widgets directly. |
| [ ] | Integrate reference masks | Existing valid `fits_ref_*.tif` files are reused and missing requested masks can be collected before dependent analysis. |
| [ ] | Integrate ROI masks | Existing valid `fits_roi_*.tif` files are reused and missing requested masks can be collected before dependent analysis. |
| [ ] | Define analysis expansion | Distance profiling expands every finalized reference/ROI label and channel into long-form rows; extraction uses references but never requests ROIs. |
| [ ] | Add per-experiment release | Finalizing the active experiment allows it to continue while the manager advances to the next queued experiment. |
| [ ] | Add conveyor scheduling | Preparation, segmentation/tracking, mask collection, and analysis overlap safely across experiments. |
| [ ] | Make conveyor the interactive default | Batch/sequential execution remains supported while GUI interactive runs default to conveyor. |
| [ ] | Add the GUI preparation lock | Processing settings remain unavailable until usable prepared images exist; the user's saved settings are not overwritten. |
| [ ] | Add CLI mask policies | Interactive, noninteractive-skip, and strict-missing-input behavior are explicit. |
| [ ] | Complete cancellation and reporting | The final report distinguishes completed, skipped, failed, omitted, and cancelled work. |
| [ ] | Verify the complete workflow | Focused unit, coordinator, headless Qt, CLI, and restart tests pass and `git diff --check` is clean. |

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
- Should interactive mode automatically select conveyor execution, reject batch
  mode, or allow a deliberately synchronous batch interaction?
- What cancellation guarantees can each task/executor realistically provide?
- How should interactive CLI invocation behave when no graphical display is
  available?

Distance-profile output uses long-form rows for every reference label/channel,
ROI label/channel, intensity channel, frame, and distance bin combination.
Each ROI is evaluated independently, and a second whole-image variant is
represented by missing ROI label/channel values. FITS normalizes mask identity
columns across analysis outputs as `ref_label_name`, `ref_channel`,
`roi_label_name`, and `roi_channel` where applicable.
