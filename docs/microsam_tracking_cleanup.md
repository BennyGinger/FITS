# µSAM tracking editor: cleanup direction

Status: design agreement following the interactive µSAM smoke test. The current
implementation is intentionally experimental and should be committed before the
cleanup described here.

## Agreed responsibilities

- Replace the legacy Add/Edit prediction path with µSAM completely.
- Keep manual brush add/remove and enclosed-area filling as deterministic mask
  operations rather than model predictions.
- Retain the existing geometry/intensity/watershed predictor for Split. µSAM
  segments a prompted object but does not directly guarantee an exact partition
  into two complete, non-overlapping masks. A two-click µSAM-assisted split can
  be evaluated later, with watershed still resolving the final partition.
- Keep registration and temporal behavior outside the µSAM inference backend.

The intended boundary is:

```text
GUI prompts
    -> registration and temporal policy
    -> headless µSAM Add/Edit backend
    -> mask ownership and validation
```

## Registration and static-only protection

OpenCV local registration transports the previous mask and centroid to the next
frame. µSAM then refines that prompt using the current image. Registration is
coarse positioning, not final segmentation.

Classify each transition into three states:

- **Confidently static:** high registration confidence, phase-correlation and
  ECC displacement agree, displacement is very small, and the result is
  plausible.
- **Moving:** meaningful displacement is supported by registration.
- **Uncertain:** conflicting or weak evidence.

Only confidently static transitions receive shape enforcement. Moving and
uncertain transitions use the registered µSAM prompt without static protection.
A starting definition of static could be displacement no larger than
`max(1-2 pixels, 5% of expected cell diameter)`, but this must be tuned on real
data and kept configurable.

For a static cell, propagate only the user's edit delta:

```python
added = edited_previous & ~original_previous
removed = original_previous & ~edited_previous

prediction |= added
prediction &= ~removed
```

Static shrinkage protection is a separate operation in the same temporal
policy. It may restore limited directional edge loss relative to the previous
accepted mask, but it must remain disabled for moving and uncertain cells.
Keeping edit propagation and shrinkage protection independent allows either to
be tuned or disabled without changing registration or µSAM.

## Headless µSAM dependency

The upstream `micro-sam` distribution currently installs GUI and broader
application dependencies such as napari, a Qt binding, magicgui, superqt,
training utilities, and tracking packages. FITS only needs model loading,
checkpoint caching, embeddings, point/mask/box prompts, and iterative logits.

This is also tracked upstream in
[`micro-sam` issue #1113: Installing micro-sam headless](https://github.com/computational-cell-analytics/micro-sam/issues/1113).
The issue was opened on 26 September 2025 for the same plugin and headless/HPC
use case. As checked on 28 September 2026, it remains open without a linked
branch or pull request, and released/current packaging still makes napari and a
Qt binding base dependencies.

Create a separately versioned, headless fork/workspace package instead of only
removing dependency declarations. Inference imports must also be separated from
GUI, training, tracking, BioImage.IO, and other unrelated modules. A suitable
layout is:

```text
micro_sam_core/
    models.py
    checkpoints.py
    embeddings.py
    prompts.py
    predictor.py
```

The core dependency set should be limited to what inference actually imports,
principally NumPy, PyTorch, the compatible SAM/MobileSAM implementation, and a
small checkpoint downloader. GUI, training, and tracking dependencies should be
optional extras if those upstream features are retained in the fork.

Development requirements for the fork:

- Preserve the upstream license, copyright, and attribution.
- Keep an `upstream` Git remote and periodically incorporate relevant fixes.
- Tag and pin known-compatible versions from FITS.
- Verify checkpoint URLs, hashes, architecture compatibility, and licenses.
- Provide CI that imports and runs inference in an environment without napari,
  PyQt, or PySide.
- Expose a small public API; do not make FITS depend on private underscore APIs
  such as `_compute_logits_from_mask`.
- Prefer a distinct distribution and import name to avoid conflicts with the
  upstream `micro-sam` package.

Develop the fork as an upstream-compatible refactoring where practical rather
than as a permanently divergent implementation. Once the headless dependency
split and clean-environment tests are working, consider proposing it upstream
as a pull request linked to issue #1113. FITS can remain pinned to the fork until
an accepted change is included in an official release; if it is not accepted,
the narrowly scoped fork remains easier to synchronize than a broad rewrite.

A Git submodule/workspace is appropriate during development. Before publishing
FITS, either publish the headless package separately, include the narrowly
scoped adapter in FITS with attribution, or contribute an accepted core/GUI
split upstream. PyPI installations do not automatically retrieve Git
submodules.

## Proposed cleanup order

1. Preserve the current experiment with integration tests and a commit.
2. Define a small Add/Edit backend interface.
3. Make µSAM the only learned Add/Edit predictor.
4. Separate deterministic brush operations from model inference.
5. Remove the legacy Add/Edit classifier/random-walker path while retaining
   `SplitPredictor`.
6. Extract registration and temporal decisions into a dedicated policy.
7. Add static/moving/uncertain classification.
8. Add static-only edit-delta propagation.
9. Add independently configurable static-only shrinkage protection.
10. Replace the full upstream dependency with the tested headless workspace
    package and verify clean installation on supported platforms.
