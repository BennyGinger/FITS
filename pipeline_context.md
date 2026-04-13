# FITS Pipeline – Architecture Context

## Overview

The FITS pipeline processes microscopy experiments in a structured, reproducible way.

The pipeline operates on **ExperimentState** objects, which represent the processing state of a single experiment unit (usually a single image series).

The pipeline is composed of independent workflow steps such as:

* `convert`
* `segment`
* `metadata_change`

Each step takes one or more `ExperimentState` objects and returns updated states.

Steps are designed to be:

* deterministic
* restartable
* filesystem-based
* resilient to folder reorganization

---

# Core Concepts

## Experiment Unit

An experiment unit corresponds to a **workdir folder** containing all artifacts produced by the pipeline for a single raw image (or series).

Example layout:

```text
Run3_test/
├── control/
│   ├── c3z1t1v3.nd2
│   └── c3z1t1v3_s1/
│       ├── fits_array.tif
│       ├── fits_mask.tif
│       └── experiment_state.json
```

---

# Path Anchoring Model

## Durable Anchor: `workdir`

All persisted paths inside `ExperimentState` are **relative to `workdir`**.

Absolute paths are reconstructed at runtime:

```python
absolute_path = workdir / relative_path
```

This ensures experiment folders can be moved without breaking the pipeline.

---

# Runtime Context

The pipeline runtime provides an **ExecutionContext** accessible through:

```python
get_ctx()
```

This includes:

```text
run_dir
user_name
logging settings
execution mode
```

`run_dir` is **not persisted**.

---

# ExperimentState

Represents pipeline progress.

Key attributes:

```text
workdir
original_image_rel
image_rel
masks_rel
completed_steps
last_error
updated_at
```

---

# Convert Step

Creates:

```text
fits_array.tif
```

Also writes structural metadata:

```text
source_channel_indices
source_channel_count
```

These define the mapping between exported channels and original raw channels.

---

# Background Subtraction Step

Reads and rewrites:

```text
fits_array.tif
```

Processes all exported channels in place.

Stores step metadata under:

```python
project_metadata["steps"]["bg_sub"]
```

Typical bg_sub step metadata includes:

```text
sigma
size
threshold
statistic
distribution
version
timestamp
```

There is no per-channel provenance block for bg_sub, because it processes the full current image artifact uniformly.

---

# Segment Step

Creates:

```text
fits_mask.tif
```

Uses:

```text
source_channel_indices
```

to maintain stable channel identity relative to the input image.

Segmentation provenance is stored in pipeline metadata under:

```python
project_metadata["steps"]["segment"]
```

including channel-aware metadata under:

```python
project_metadata["steps"]["segment"]["channels"]
```

and mask channel identity under:

```python
project_metadata["steps"]["segment"]["mask_source_channel_indices"]
```

---

# Channel Identity Model

## Image

```text
source_channel_indices
source_channel_count
```

These describe how the current saved image channels map back to the original raw image.

## Step / Derived Artifact Identity

Stored in pipeline project metadata:

```python
project_metadata["steps"][step_name]
```

For channel-aware mask-producing steps such as segmentation, this includes:

```text
mask_source_channel_indices
channels
```

This separation allows:

* partial segmentation
* incremental updates
* stable channel identity independent of labels
* clear distinction between generic I/O metadata and workflow provenance

---

# Incremental Mask Behavior

When segment is re-run:

* existing mask is loaded if present
* previously saved mask channel identity is read from:

```python
project_metadata["steps"]["segment"]["mask_source_channel_indices"]
```

* new channels are merged into the correct position
* existing channels are preserved
* per-channel step metadata is merged by source channel index
* `mask_source_channel_indices` is updated inside the segment step metadata

Channel identity is determined by **source channel index**, not by label.

---

# Metadata Architecture

## FITS I/O Metadata

Stored in the TIFF private payload and mirrored into ImageJ-readable metadata where relevant.

Owned by `fits_io`.

Typical `fits_io` block:

```python
fits_io.version
fits_io.axes
fits_io.channel_labels
fits_io.n_channels
fits_io.z_projection
fits_io.compression
fits_io.source_channel_indices
fits_io.source_channel_count
```

This block represents **technical image / artifact metadata** and is preserved across in-place rewrites.

## Pipeline Metadata

Stored under:

```text
project_metadata
```

Owned by the `fits` workflow layer.

Top-level structure:

```python
project_metadata["pipeline"]
project_metadata["steps"]
```

## Pipeline Block

Contains pipeline-wide provenance such as:

```text
distribution
version
timestamp
user_name
```

## Steps Block

Contains one entry per workflow step, for example:

```python
project_metadata["steps"]["convert"]
project_metadata["steps"]["bg_sub"]
project_metadata["steps"]["segment"]
```

Each step block contains provenance such as:

```text
distribution
version
timestamp
```

plus step-specific metadata.

Examples:
* convert:
    * custom conversion metadata if provided
* bg_sub:
    * sigma
    * size
    * threshold
    * statistic
* segment:
    * mask_source_channel_indices
    * channels[source_idx] = per-channel segmentation metadata

---

# Workflow Layering

## Root APIs

```text
convert.py
segment.py
metadata_change.py
```

These are orchestration-only.

They:

* resolve runtime context
* load data
* run the processing engine
* build/update pipeline-owned `project_metadata`
* save through `fits_io`

They no longer build old writer provenance payloads directly.


## Workflows/metadata

This layer owns pipeline metadata construction and loading.

Typical responsibilities:

* load existing `project_metadata` from an artifact
* build / update pipeline-level provenance
* build / update step-level metadata
* merge channel-aware step metadata
* preserve prior metadata during in-place rewrites

This layer is the canonical place for workflow provenance assembly.

## Workflows/arrays

### `channel_identity.py`

* label ↔ source index conversion
* exported channel identity resolution

### `channel_metadata.py`

* shaping per-channel workflow metadata
* building "channels" metadata blocks for channel-aware steps

### `channel_merge.py`

* pure array merge logic
* no save logic
* no workflow provenance logic

### `mask_output.py`

* load existing mask
* read prior segment mask source channel indices from step-level project metadata
* prepare merged mask output (array + axes + labels)
* preserve stable mask channel identity across incremental runs


### converter / loading helpers

* array extraction from FITS artifacts
* flatten / rebuild helpers for frame-wise processing
* shape / axis normalization helpers

## workflows/engines

### `provencance.py`

Contains low-level provenance utilities and `StepProfile`.

It may provide utilities such as:

* version lookup
* UTC timestamp generation
* provenance stamp construction

It no longer acts as the old workflow save payload entrypoint.

### `run_decision.py`

* determine what remains to run
* supports both:

  * full-step completion
  * channel-level completion


### `executor.py`

* execution backend dispatch
* ordered / unordered execution
* worker fan-out

---

# Convert Execution Flow

```text
1. validate input image
2. open reader
3. resolve export channels
4. extract array
5. build initial project_metadata through workflow metadata builder
6. save fits_array.tif through fits_io using project_metadata
7. update state
```

---

# Background Subtraction Execution Flow

```text
1. validate image
2. open reader
3. decide whether step must run
4. load current image array
5. flatten to processing frames
6. run background subtraction
7. rebuild output array
8. load existing project_metadata from current artifact
9. update bg_sub step metadata through workflow metadata builder
10. save fits_array.tif through fits_io using project_metadata
11. update state
```

---

# Segment Execution Flow

```text
1. validate image
2. open reader
3. resolve requested channels
4. compute pending channels
5. load image data
6. run segmentation
7. build per-channel metadata
8. load existing mask artifact if present
9. merge mask arrays by source channel index
10. load existing project_metadata from mask artifact if present
11. update segment step metadata through workflow metadata builder
12. save fits_mask.tif through fits_io using project_metadata
13. update state
```

---

# Error Handling & Logging

## Design Principle

**Failures must never be silent, but must not stop the entire batch.**

A failure in one experiment:

* must be visible immediately in the console
* must be logged with full traceback
* must mark the corresponding `ExperimentState` as failed
* must **not stop processing of other experiments**

---

## Execution Model

### 1. Low-level modules (helpers, fits_io, channel logic)

* must **raise exceptions on failure**
* may log using `logger.exception(...)`
* must **not swallow errors**
* must **not decide pipeline continuation**

---

### 2. Per-state workflow execution

Each step processes one `ExperimentState` at a time.

At this boundary:

* exceptions are **caught once**
* full traceback is logged
* a concise error is printed to console
* the state is updated using `with_error(...)`
* execution continues with next state

Pattern:

```python
try:
    ...
    return [updated_state]
except Exception as e:
    logger.exception(...)
    print("[ERROR] ...")
    return [state.with_error(...)]
```

---

### 3. Batch / pipeline level

* continues processing remaining states
* does not stop on single failure
* may optionally summarize successes/failures at the end

---

## Console Behavior

On failure, user must immediately see:

```python
[ERROR] Step 'segment' failed for <workdir>: <error message>
```

Traceback remains in log file.

---

## State Behavior

* `ExperimentState` is updated **only on success or explicit failure**
* failed states contain:

  * `last_error`
  * failed step name
* failed steps are **not marked as completed**

---

## Expected Behavior

* no silent failures
* no missing output without explanation
* one bad experiment does not stop the pipeline
* clear visibility for debugging

---

# Design Principles

## Deterministic execution

Steps produce consistent outputs.

## Restartability

* completed steps are skipped
* channel-level completion is supported where relevant
* segmentation restartability is based on stored step-level channel provenance

## Filesystem-first

Artifacts are files:

```text
fits_array.tif
fits_mask.tif
```

## Thin pipeline layer

Pipeline logic should remain simple and rely on:

* `fits_io` for I/O and technical metadata persistence
* workflow metadata builder for pipeline provenance
* workflows/arrays for channel logic

Avoid over-engineering.

## Ownership separation

Keep this rule strict:

* `fits_io` owns technical image / artifact metadata
* `fits` workflow layer owns semantic provenance in project_metadata

Do not push workflow provenance back into `fits_io`.

---

# Coding Style Requirement

Do not spread function parameters across multiple lines.

Avoid:

```python
def myfunc(
    param1,
    param2,
    param3,
):
```

Prefer:

```python
def myfunc(param1, param2, param3):
```

Apply the same rule to function calls whenever reasonably possible.

Same with imports.

Avoid:

```python
import (
    module1,
    module2,
)
```

Prefer:

```python
import module1, module2
```
