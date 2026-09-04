# FITS Pipeline Architecture Context

## Purpose

FITS is the orchestration layer for a microscopy image-processing pipeline. It discovers raw images, creates durable experiment states, validates user settings, runs the enabled workflow steps, and records enough state and metadata to restart safely.

The project deliberately keeps image-processing implementations in independent packages. Those packages must remain usable without importing or knowing about `fits`:

| Package | Responsibility |
| --- | --- |
| `fits_io` | Read, normalize, select, merge, and write microscopy image data and technical image metadata |
| `bg_sub` | Background subtraction |
| `stackalign` | Time-wise and channel-wise image registration |
| `cellpose_kit` | Cellpose setup and segmentation |
| `tracklink` | Object tracking |
| `progress_bar` | Terminal progress display and log handling |

The code in `src/fits/` adapts these generic modules to the FITS workflow. Pipeline state, step ordering, restart decisions, configuration, and provenance belong in `fits`, not in the independent packages.

`fits_io` is the closest integration point because every task uses it to exchange artifacts, channel identity, axes, and metadata. Its API can serve the main workflow, but it must not depend on `ExperimentState`, FITS settings, task names, scheduling, or other `fits` mechanics.

## Design Priorities

1. Keep the pipeline and module APIs simple.
2. Keep processing packages independent of FITS orchestration.
3. Make artifacts and saved state portable and restartable.
4. Put each responsibility in one clear layer.
5. Add abstractions only when they remove real duplication or enable a concrete extension.

## Repository Layout

```text
fits/
├── src/fits/
│   ├── pipeline.py             # top-level startup
│   ├── environment/            # discovery, durable state, logging, constants
│   ├── settings/               # TOML loading, validation, overwrite cascade
│   ├── tasks/                  # adapters from FITS state/settings to modules
│   ├── workflows/engines/      # registry, run decisions, executors, scheduler
│   └── workflows/metadata/     # pipeline provenance models
├── fits_io/                    # independent workspace package / submodule
├── bg_sub/                     # independent workspace package / submodule
├── stackalign/                 # independent workspace package / submodule
├── cellpose_kit/               # independent workspace package / submodule
├── tracklink/                  # independent workspace package / submodule
├── progress_bar/               # independent workspace package / submodule
└── tests/                      # FITS integration and workflow tests
```

The independent modules are workspace dependencies, not internal folders of the `fits` Python package.

## Top-Level Pipeline Flow

`fits.pipeline.start_pipeline()` is the application entry point:

```text
load TOML settings
    ↓
resolve run directory, runtime mode, and logging
    ↓
discover supported raw images
    ↓
apply the overwrite cascade
    ↓
load saved ExperimentState files and create states for new inputs
    ↓
run enabled steps in batch or conveyor mode
    ↓
return/log terminal experiment states
```

`run_dir` and runtime/logging configuration are process inputs. There is no global `ExecutionContext` or `get_ctx()` object.

## Workflow Order and Artifacts

The canonical order is defined once by `WORKFLOW_ORDER`:

```text
convert
→ register_time
→ register_channel
→ bg_sub
→ segment
→ track
```

The artifact contracts are:

| Step | Input artifact | Output artifact | Filename |
| --- | --- | --- | --- |
| `convert` | `raw_image` | `image` | `fits_array.tif` |
| `register_time` | `image` | `image` | `fits_array.tif` |
| `register_channel` | `image` | `image` | `fits_array.tif` |
| `bg_sub` | `image` | `image` | `fits_array.tif` |
| `segment` | `image` | `segmentation` | `fits_mask.tif` |
| `track` | `segmentation` plus `image` | `tracking` | `fits_track.tif` |

Registration and background subtraction intentionally rewrite the current image artifact. Segmentation and tracking create derived artifacts.

## ExperimentState

`ExperimentState` is an immutable dataclass representing one experiment branch. Its durable fields are:

```text
workdir
artifacts
completed_steps
updated_at
metadata (FitsMeta)
```

`artifacts` maps semantic artifact kinds to paths:

```python
{
    "raw_image": Path(...),
    "image": Path(...),
    "segmentation": Path(...),
    "tracking": Path(...),
}
```

Artifact paths are stored relative to `workdir` in `experiment_state.json` and resolved to absolute paths at runtime. Relative paths may contain `..`, allowing the original raw file to remain outside a series-specific output directory while preserving portability of the surrounding experiment tree.

State changes return a new object:

- `with_metadata(...)` returns a state with updated `FitsMeta`.
- `with_complete_step(...)` records an artifact and completed step.
- `save_state()` atomically writes `experiment_state.json` through a temporary file and `os.replace`.
- `load_state(workdir)` treats the supplied workdir as authoritative.

The state currently does not persist a `last_error` field. A failed task logs the exception, prints a concise error, and returns no output state.

## Experiment Branching

Before conversion, a raw file is represented by a state whose workdir is the raw file's parent. `fits_io.split_series()` may produce one or several readers. Conversion creates one output state per series and moves each branch's authoritative workdir to the saved artifact's parent.

Typical single-series layout:

```text
experiment/
├── input.nd2
└── input_s1/
    ├── fits_array.tif
    ├── fits_mask.tif
    ├── fits_track.tif
    └── experiment_state.json
```

The exact series folder name is decided by `fits_io`, not by the orchestration layer.

## Discovery and Restartability

Discovery recursively finds extensions supported by `fits_io` and excludes generated files whose names start with `fits_`.

Unless conversion is enabled with `overwrite = true`, startup:

1. loads valid `experiment_state.json` files below `run_dir`;
2. skips invalid saved states with a warning;
3. creates fresh states only for raw images not already represented by saved states.

If conversion overwrite is enabled, saved states are ignored and branches are rebuilt from raw inputs.

`decide_run()` implements two restart modes:

- Whole-step: complete only when the step is in `completed_steps` and its output artifact exists.
- Channel-level: complete per source channel using the step's channel metadata.

`overwrite = true` clears completion for the current decision. Settings resolution also applies an overwrite cascade to downstream steps so stale derived results are not reused after an upstream rewrite.

## Step Registry

`workflows/engines/registry.py` is the integration map. Each `StepSpec` binds:

- a `StepProfile` (`step_name`, owning distribution, input/output artifact, output filename);
- a Pydantic settings model;
- a single-state task runner;
- a CPU or GPU pool;
- an optional concurrency cap.

This keeps the execution engines generic. Adding a step normally requires a constant/order entry, settings model, task adapter, and registry entry. The processing package itself should not need FITS-specific changes.

## Execution Modes

### Batch

Batch mode runs each enabled step across all current states before advancing to the next step. Per-step execution can be serial, threaded, or process-based according to its validated settings.

### Conveyor

Conveyor mode advances experiment branches independently. It uses separate thread pools for CPU and GPU work so one branch can move downstream while another is still upstream. GPU work is serialized; individual steps may additionally declare a concurrency cap. `register_time` currently has a cap of one.

Both modes use the same workflow order, registry, settings models, task functions, and state contracts.

## Task Adapter Contract

Files under `src/fits/tasks/` are thin integration adapters. A task receives:

```python
(settings, exp_state, step_profile) -> list[ExperimentState]
```

A task should:

1. resolve its input artifact from the state;
2. ask `decide_run()` whether work is pending;
3. use `FitsIO` to read/select normalized data;
4. call the independent processing module;
5. use `FitsIO` to merge and save the result;
6. add pipeline metadata and mark the step complete;
7. atomically save the new state;
8. return zero, one, or multiple output states.

Returning a list is intentional: most tasks return one branch, conversion may split a multi-series input into several branches, and failure currently returns an empty list.

Task adapters may know both FITS and a processing module. Processing modules must know neither FITS state nor the scheduler.

## Current Step Behavior

### Convert

- Opens the raw source through `FitsIO`.
- Resolves channel labels and export selection.
- Splits multi-series inputs.
- Prepares/saves `fits_array.tif`, including optional Z projection and compression.
- Produces one durable state per series.

### Register Time

- Resolves a registration preset from context, with optional backend/method overrides.
- Fits time-wise transforms with `stackalign.RegisterModel` and applies them to the full image.
- Uses one fitting channel for multichannel input.
- Rewrites `fits_array.tif` and records shared step parameters.

### Register Channel

- Resolves the channel-registration preset and optional overrides.
- Fits and applies per-channel transforms with `stackalign.RegisterModel`.
- Rewrites `fits_array.tif` and records shared step parameters.

### Background Subtraction

- Selects included channels through `FitsIO`.
- Calls the independent `bg_sub` function.
- Rebuilds the full array so excluded channels are preserved.
- Rewrites `fits_array.tif`.
- Stores shared metadata when all channels run, or channel metadata when channels are excluded.

### Segment

- Resolves requested labels to stable source channel indices.
- Runs only pending channels.
- Uses the cached `cellpose_kit` wrapper.
- Optionally includes a nuclear channel as model input without making it a mask output channel.
- Merges new masks with an existing `fits_mask.tif` by source channel index.
- Records per-channel parameters and completion.

### Track

- Reads the segmentation artifact and the corresponding image channels.
- Runs only pending channels with `tracklink.TrackModel`.
- Filters tracks by length when configured.
- Merges results with an existing `fits_track.tif` by source channel index.
- Records per-channel parameters and completion.

## Metadata Ownership

There are two distinct metadata concerns.

### Technical artifact metadata: owned by `fits_io`

Examples include axes, channel labels, source channel indices, channel count, artifact kind, compression, and other details required to interpret an image file. `fits_io` must preserve this information through reads, selections, merges, and rewrites.

### Pipeline provenance: owned by `fits`

`FitsMeta` is stored in `ExperimentState` and passed to `fits_io` as `custom_metadata` when an artifact is written. Its serialized structure is:

```python
{
    "pipeline_meta": {
        "user_name": ...,
        "created_by": "fits",
        "version": ...,
        "timestamp": ...,
    },
    "steps": {
        "segment": {
            "step_name": "segment",
            "created_by": "cellpose-kit",
            "version": ...,
            "timestamp": ...,
            "params": {},
            "channels": {
                "1": {
                    "channel": 1,
                    ...,
                    "timestamp": ...,
                }
            },
        }
    },
}
```

`FitsMeta`, `RunMetadata`, `StepsMetadata`, and `ChannelStepMeta` are immutable value-style models. Updating a step preserves metadata for other steps and previously processed channels.

Do not move workflow provenance construction into `fits_io`. `fits_io` accepts and persists an opaque custom metadata mapping; `fits` defines what that mapping means.

## Channel Identity

Labels are user-facing selectors. Source channel indices are the durable identity used for provenance, incremental segmentation/tracking, and mask merging.

The rule is:

```text
label → resolve through fits_io → source index → persist/merge by source index
```

Never use a label alone as the identity of a derived channel. Labels may change; source indices preserve the relationship to the converted image.

Shared whole-image parameters are stored in a step's `params`. Channel-specific parameters are stored in `channels[str(source_index)]`. `ExperimentState.completed_channels()` reads those channel records.

## Error Handling

Independent modules and `fits_io` should fail fast by raising useful exceptions. They must not decide whether the pipeline continues.

The current FITS task boundary catches exceptions, writes the full traceback to logging, prints a concise message, and returns an empty state list:

```text
[ERROR] Step '<step>' failed for <experiment>: <message>
```

An empty result removes that branch from subsequent work while other branches continue. Failed steps are not marked complete and no error is currently saved in `ExperimentState`.

Configuration, registry, or scheduler failures outside a task boundary are allowed to propagate because they indicate a pipeline-level problem rather than one bad experiment.

## Boundary Rules for Future Work

- A reusable processing package accepts arrays and explicit domain parameters; it does not accept `ExperimentState` or FITS settings models.
- `fits_io` owns file formats, normalized axes, channel selection/identity, merging, and technical metadata persistence.
- `src/fits/tasks` owns adaptation between pipeline state/settings and module APIs.
- `workflows/engines` owns execution policy, not image processing.
- `workflows/metadata` owns pipeline provenance, not file-format metadata.
- `environment` owns discovery and durable experiment state.
- Prefer direct functions and small dataclasses over plugin frameworks or deep class hierarchies.
- Keep one authoritative workflow order and one registry.
- Preserve existing artifacts and metadata during incremental channel work.
- Add a new abstraction only when at least one concrete use requires it.

## Practical Extension Checklist

When adding a new independent module or workflow step:

1. Give the module a FITS-agnostic array/domain API and its own focused tests.
2. Add the step name and its position to `WORKFLOW_ORDER`.
3. Add a validated settings model.
4. Write one thin task adapter.
5. Register its artifact contract, distribution, runner, and execution pool.
6. Record provenance with `ExperimentState.with_metadata()`.
7. Save through `FitsIO` when the output is an image artifact.
8. Test skip, overwrite, failure, state persistence, and channel-incremental behavior as applicable.

This is the intended scaling path: independent modules stay small, while FITS remains a thin, explicit composition layer.
