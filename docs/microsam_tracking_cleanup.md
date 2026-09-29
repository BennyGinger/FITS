# µSAM tracking editor: cleanup direction

Status: the headless µSAM Add/Edit backend is integrated and working. The FITS
integration is committed as `d12cb23`, and the fork revision used by FITS is
`8b3b337`. Focused FITS tests pass, a real-image MobileSAM prediction was
successful, and the TrackEdit behavior has been checked manually.

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

The packaging work is tracked by
[`micro-sam` issue #1113: Installing micro-sam headless](https://github.com/computational-cell-analytics/micro-sam/issues/1113).
The implementation has now been proposed upstream in
[`micro-sam` PR #1384: Make GUI and application dependencies optional](https://github.com/computational-cell-analytics/micro-sam/pull/1384).

The fork keeps the existing `micro_sam` distribution and import name. Its base
installation contains the packages required for prompt-based inference, while
the existing GUI, training, tracking, BioImage.IO, and other application
dependencies are available through:

```bash
pip install micro-sam[full]
```

Optional `imageio` and `python-elf` imports are loaded only inside the functions
that use them. A clean-install CI job checks that the inference API imports
without napari, Qt, magicgui, superqt, torch-em, trackastra, or python-elf. The
normal full test jobs install `micro-sam[full]` so the upstream test suite keeps
its previous dependency coverage.

FITS currently keeps the fork as the `micro-sam-headless` Git submodule and
resolves `micro-sam` to that local path with uv. `micro-sam` and `mobile-sam`
remain in the default-installed `dev` group while FITS has only one user. This
is sufficient for current FITS development but is not a publication solution:
PyPI installations do not retrieve Git submodules or apply uv source overrides.

Until the upstream PR is reviewed, FITS should remain pinned to the tested fork
revision. If the change is accepted and released, FITS can depend on the
official release. Before distributing FITS to other users, move the runtime
dependencies out of `dev` and verify how MobileSAM will be installed.

## Proposed cleanup order

1. **Done:** preserve the experiment with integration tests and a commit.
2. **Done:** define a small injectable Add/Edit backend interface.
3. **Done:** make µSAM the TrackEdit Add/Edit backend and verify it on real data.
4. **Done:** create and test the headless dependency split; submit upstream PR
   #1384.
5. Separate deterministic brush operations from model inference.
6. Remove the legacy Add/Edit classifier/random-walker path while retaining
   `SplitPredictor`.
7. Extract registration and temporal decisions into a dedicated policy.
8. Add static/moving/uncertain classification.
9. Add static-only edit-delta propagation.
10. Add independently configurable static-only shrinkage protection.
11. After an upstream release, replace the fork pin and prepare the dependencies
    for distributing FITS to other users.
