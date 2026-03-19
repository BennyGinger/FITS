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

```text
absolute_path = workdir / relative_path
```

This ensures experiment folders can be moved without breaking the pipeline.

---

# Runtime Context

The pipeline runtime provides an **ExecutionContext** accessible through:

```text
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

# Segment Step

Creates:

```text
fits_mask.tif
```

Uses:

```text
source_channel_indices
```

to maintain stable channel identity.

Mask structure is defined by:

```text
mask_source_channel_indices
```

---

# Channel Identity Model

## Image

```text
source_channel_indices
source_channel_count
```

## Mask

```text
mask_source_channel_indices
```

This separation allows:

* partial segmentation
* incremental updates
* stable channel identity independent of labels

---

# Incremental Mask Behavior

When segment is re-run:

* existing mask is loaded if present
* new channels are merged into correct position
* existing channels are preserved
* `mask_source_channel_indices` is updated

---

# Metadata Architecture

## Viewer Metadata

Used by ImageJ:

```text
axes
Labels
resolution
```

## Private Metadata

Stored in TIFF tag:

```text
status
user_name
source_channel_indices
source_channel_count
mask_source_channel_indices
payload[step]["channels"]
```

---

# Workflow Layering

## Root APIs

```text
convert.py
segment.py
metadata_change.py
```

These are orchestration-only.

---

## workflows/channels

### `metadata.py`

* label ↔ source index conversion
* channel metadata construction

### `channel_merge.py`

* pure array merge logic
* no metadata or saving logic

### `persistence.py` (conceptually: mask output)

* load existing mask
* prepare merged output (array + axes + labels)
* build mask structural metadata
* merge step metadata

---

## workflows/engines

### `run_decision.py`

* determine what remains to run
* supports both:

  * full-step completion
  * channel-level completion

---

# Segment Execution Flow

```text
1. validate image
2. open reader
3. resolve requested channels
4. compute pending channels
5. load image data
6. run segmentation
7. build channel metadata
8. prepare mask output
9. merge metadata
10. save TIFF
11. update state
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

```text
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

```text
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
* channel-level completion supported via `mask_source_channel_indices`

## Filesystem-first

Artifacts are files:

```text
fits_array.tif
fits_mask.tif
```

## Thin pipeline layer

Pipeline logic should remain simple and rely on:

* `fits_io` for I/O and metadata
* workflows/channels for channel logic

Avoid over-engineering.

---

# Current Pipeline Tree

```text
.
├── cellpose_kit
│   ├── src
│   │   └── cellpose_kit
│   │       ├── backend
│   │       └── workflow
│   └── tests
│       ├── backend
│       └── workflow
├── fits_io
│   ├── src
│   │   └── fits_io
│   │       ├── metadata
│   │       ├── readers
│   │       └── writers
│   └── tests
│       ├── metadata
│       ├── readers
│       └── writers
├── progress_bar
│   ├── src
│   │   └── progress_bar
│   └── tests
├── src
│   └── fits
│       ├── cli
│       ├── environment
│       ├── settings
│       └── workflows
│           ├── channels
│           └── engines
└── tests
    ├── environment
    └── workflows
        ├── channels
        └── engines
```

---

# Coding Style Requirement

Do not spread function parameters across multiple lines.

Avoid:

```text
def myfunc(
    param1,
    param2,
    param3,
):
```

Prefer:

```text
def myfunc(param1, param2, param3):
```

Apply the same rule to function calls whenever reasonably possible.

Same with imports.

Avoid:

```text
import (
    module1,
    module2,
)
```

Prefer:

```text
import module1, module2
```
