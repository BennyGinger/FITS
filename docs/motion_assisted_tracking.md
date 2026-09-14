# Motion-assisted cell tracking and segmentation

Status: concept and proposed evaluation plan; implementation pending.

Priority: evaluate and port the tracking-only path of Baxter Algorithms,
including its `ctc2024` update, before developing a new tracking algorithm.

Historical reference: [legacy BaxTrack integration](baxter_legacy_context.md)
records the 2023 Docker commit, Python/MATLAB call contract, settings, and
retrieval commands for the old pipeline.

## Objective and experimental context

Improve tracking of migrating cells within tissue, particularly when cells
crowd around a chemoattractant source, cross paths, disappear temporarily, or
become a single segmented region. Use information across time to help distinguish
cells from tissue structures that look similar in individual images, and allow
tracking evidence to guide segmentation corrections.

Most current downstream analyses use maximum-intensity projections. Original
Z stacks could nevertheless help tracking: two cells that overlap in XY may
remain distinguishable in Z. Preserve that information when available, even if
the analysis and initial viewer continue to use projections.

Prefer existing pretrained models and mathematical algorithms. Training a large
new neural network is not the initial goal. Improvement over Trackastra is a
hypothesis to test on real experiments, not an assumed outcome.

## Proposed approach

Start with Cellpose segmentation feeding a Baxter-derived tracking backend.
The previous pipeline already used Cellpose masks as Baxter input through a
MATLAB runtime integration. The user recalls useful performance on migrating
cells and use of Z information to resolve trajectories. Installation and
maintenance across machines, including a Gurobi dependency and recurring license
renewal, made that workflow burdensome. These are reports about the previous
integration; audit which dependencies the selected 2024 tracking path actually
requires rather than assuming all are intrinsic to its C++ linker.

The target is a Python-callable backend without MATLAB/Runtime or a mandatory
Gurobi installation. Reuse suitable C++ algorithms and translate the necessary
MATLAB preparation and scoring code. Keep Trackastra available for comparison.

After evaluating Baxter, consider these additions only for demonstrated gaps:

1. **Image motion:** estimate local displacement between frames using classical
   optical flow or local image correlation. Use it to predict cell positions or
   move previous masks toward their expected locations.
2. **Uncertain association:** combine motion, recent trajectories, appearance,
   segmentation quality, and optionally Trackastra association scores to evaluate possible
   links. Allow short detection gaps and reconsider ambiguous assignments using
   later frames.
3. **Segmentation feedback:** use trusted tracks to propose local corrections to
   missed, merged, or fragmented masks, then reassess the links against the
   corrected proposals and image evidence.

Conceptually, the longer-term workflow is:

```text
Images + initial segmentation
            |
            v
Baxter tracking core + existing scoring/motion evidence
            (additional motion/Trackastra cues if justified)
            |
            v
Tracking with short gaps and uncertain assignments
            |
            v
Identify ambiguous regions -> propose local segmentation repairs
            ^                              |
            |_____ reassess associations __|
            |
            v
Tracks + masks + uncertainty/status information -> review and analysis
```

The feedback loop should have a small, explicit iteration limit. A predicted
position is supporting evidence, not proof that a cell or boundary is present.

## What the mathematical components would do

- **Optical flow / local correlation:** estimate movement of image patterns.
  This can make overlap informative after compensating for displacement.
  Account for tissue drift and deformation; changing brightness and overlapping
  cells can also make motion estimates unreliable.
- **Motion prediction:** estimate the next position and its uncertainty from
  recent observations. A short-term velocity model is a baseline, not an
  assumption of straight trajectories throughout the experiment. Uncertainty
  should grow during gaps and accommodate turning or stopping.
- **Linear assignment (Hungarian-style matching):** choose a consistent set of
  matches from a table of connection costs. It does not itself define motion,
  repair segmentation, or preserve several explanations of a crossing. Include
  explicit options for missed detections, new tracks, and track endings.
- **Optimization over several frames / multiple hypotheses:** use future
  evidence before committing to difficult identities. Graph optimization chooses
  a solution across a temporal window; multi-hypothesis tracking explicitly
  retains competing explanations. These are alternatives to evaluate, not
  interchangeable names or requirements to implement both.

For example, if two cells enter one segmented blob and separate later, preserve
the possibility that two cells remain present. Compare their possible outgoing
identities using the surrounding frames instead of immediately terminating one
track or treating the event as biological fusion/division. Limit candidate links
and retained hypotheses to keep crowded sequences computationally manageable.

Treat association scores as scores until their probabilistic interpretation has
been checked. Combining correlated cues does not automatically produce a
calibrated probability.

## Using Z while retaining a projection-based workflow

Retain the original time/Z stacks, axis metadata, voxel spacing, frame interval,
and the mapping to derived projections. Audit Baxter's existing 3D tracking path
in the first phase; preserve supported Z behavior in the port. Use simple 2D
cases for initial checks and include 3D examples in validation.

A practical intermediate option is to inspect local Z information only around
ambiguous XY encounters. Depth profiles or local 3D detections might distinguish
cells that the projection combines. This remains a proposal: it requires enough
axial resolution and signal, and it must be compared with full 3D tracking where
appropriate. A single brightest-Z value per projected object may be misleading
when cells span several planes or overlap.

Prefer reusing Baxter's existing 3D capabilities where applicable before building
a separate depth-assisted method. Verify the required input masks and coordinates.
Distances must account for unequal XY/Z voxel spacing. Time offsets during Z
acquisition can matter for rapidly moving cells. Access to Z data alone does not
guarantee an unbroken identity through an encounter.

A 2D label image cannot represent two different track IDs at the same pixel.
Preserve the authoritative track/observation records and any available 3D masks
separately from the projected display. Define an explicit export policy for
overlapping projections; retaining both identities does not guarantee that
existing 2D intensity or shape measurements can separate their contributions.

## Data and package boundaries

- `tracklink` remains the home for linking algorithms, with a Baxter-derived
  backend as the first priority. A later experimental backend may combine
  pretrained Trackastra associations with motion and alternative assignment logic.
- FITS coordinates images, segmentation, tracking, local segmentation repair,
  contexts, artifact saving, and provenance. Avoid package dependencies that
  make segmentation and tracking import each other.
- Preserve initial segmentation and automatic results so corrections can be
  compared with their inputs. Keep masks, track assignments, and derived track
  summaries consistent when detections change.
- Represent observed, missing/predicted, repaired, and manually corrected
  observations distinctly. A stable-label movie alone is insufficient to retain
  gap status, competing identities, or overlapping projected objects.
- The proposed manual viewer supplies review, corrections, and reference
  annotations. It should eventually display uncertain encounters and Z evidence.

Bridging an identity gap does **not** require synthesizing a mask in the missing
frames. The static-cell shape rejection and interpolation stage discussed
separately is not the default treatment for migrating cells. Any inferred mask
must remain distinguishable from an observed segmentation in subsequent analysis.

## Suggested sequence of action

### 1. Audit and prototype Baxter's 2024 tracking-only path

Use the upstream `ctc2024` branch as a required starting point and pin the exact
revision. Inspect changes relative to older versions; do not port only the older
master implementation and assume it includes the 2024 improvements.

Trace the path from externally supplied Cellpose masks through detection/feature
preparation, candidate generation, scoring, C++ track linking, and output
conversion. Identify any cluster correction required to reproduce that path,
and how it uses Z information. Exclude the MATLAB GUI and unrelated analysis.

Audit MATLAB toolbox calls, MEX interfaces, Gurobi calls, and third-party
licenses. Determine whether solver dependencies are required for tracking or
only for optional preparation/optimization. Where a required solver must be
replaced, select an appropriate freely redistributable alternative and validate
its formulation and behavior; replacing an optimizer is not automatically
equivalent. Retain upstream attribution and applicable license notices.

Prefer retaining the C++ linking core and exposing it with a Python binding
such as pybind11. Replace MATLAB-specific interfaces and translate only the
necessary MATLAB logic into Python. Establish whether the core can compile
independently before committing to a broader port. Include portable builds for
the FITS target machines in the feasibility assessment.

There is no working MATLAB installation available, so direct MATLAB/Python
comparison is optional, not a prerequisite. Seek any saved old results or
upstream reference outputs with matching inputs/settings. Otherwise validate
with hand-checkable synthetic cases, small graph problems with independently
known solutions, annotated real clips, and CTC reference data. Check crossings,
gaps, clustered detections, Z separation, indexing, units, and output identity
consistency. Distinguish demonstrated tracking accuracy from exact equivalence
to MATLAB, which cannot be claimed without suitable reference results.

Deliverable: a dependency map, assessment of 2024 and 3D coverage, and a minimal
Python-callable tracking prototype accepting existing segmentation. Its target
runtime requires neither MATLAB nor Gurobi. Report unresolved dependencies or
unverified behavior before expanding the port. Use the benchmark below to guide
completion; building a new probabilistic tracker remains a later option.

### 2. Assemble representative clips and reference annotations

Select short clips covering isolated migration, sharp turns, stationary cells,
tissue motion, dense crowds, crossings, merged masks, missed detections, and
structures mistaken for cells. Include original Z stacks for selected projection
overlaps. Record imaging scale and timing and whether cell division is expected.

Annotate identities and difficult events; add reference masks for a smaller
subset to assess boundary corrections. Explicitly mark cases a human cannot
resolve. Reserve separate experiments for evaluation after tuning.

Deliverable: a small reproducible benchmark, supported by the manual editor when
available. Annotations initially serve evaluation and parameter tuning rather
than neural-network training.

### 3. Evaluate the Baxter port against Trackastra

Complete the selected tracking path and compare Baxter and Trackastra on the
same Cellpose masks and annotated clips. Include 2D and supported 3D cases, and
measure installation reproducibility, runtime, and memory as well as accuracy.

Compare the current configuration with suitable existing linking options and
short gaps before developing new algorithms. The inspected installation
separates association prediction from linking and exposes `delta_t` in candidate
graph construction; the FITS wrapper currently does not pass it and therefore
uses its default of one frame.

Verify prediction-window coverage, candidate pruning, and gap behavior through
graph conversion and export. Increasing `delta_t` alone is not a complete
prediction-based gap policy. Check whether required prediction access relies on
private APIs before designing an adapter around it.

Deliverable: validated Baxter backend, measured Trackastra baseline, and a
categorized set of remaining failures. Decide which later phases are warranted.

### 4. Test additional motion-assisted linking with fixed segmentation

First identify the motion evidence already used by the ported Baxter path.
Measure whether additional image displacement estimates improve it. Compare
Baxter, Trackastra, and justified extensions, including combined scores if useful.
Keep input masks identical so linking gains
can be separated from segmentation changes. Tune search ranges and short-gap
limits using frame timing and observed movement.

Deliverable: evidence that image motion improves identity continuity enough to
justify the extra runtime and settings.

### 5. Extend ambiguous-encounter handling where needed

Assess the temporal and Z handling already present in Baxter before adding
a limited temporal optimization window or bounded multiple hypotheses.
Use observations before and after crossings and distinguish missing detections
from track endings. Test local Z information on a matched subset to measure its
additional benefit. Keep unresolved encounters visible for manual review.

Deliverable: fewer identity switches through crowding, with explicit uncertainty
and manageable computation. Extend existing 3D handling only where needed.

### 6. Add targeted segmentation feedback

Use trusted neighboring observations and motion/depth predictions to propose
local repairs: recover a missed detection, split a merged region, or reunite
fragments. Possible tools include seeded watershed or locally rerunning the
existing segmenter with alternative settings. Accept proposals only when image
and temporal evidence support them; cap feedback iterations.

Deliverable: improved segmentation and tracks, measured against fixed-mask
tracking and annotated boundaries. Do not enforce static consensus shapes on
migrating cells or let propagated errors reinforce themselves indefinitely.

### 7. Integrate the validated approach into FITS

Expose experiment contexts and a small number of meaningful controls only after
defaults have been tested. Record resolved settings and algorithm versions.
Support review in the tracking editor and define how gaps, inferred masks, and
projected overlaps affect downstream measurements.

Deliverable: a reproducible optional workflow with documented limits. Retain
standard Trackastra as a baseline and usable alternative.

## How to judge success

Measure detection errors, segmentation quality on annotated frames, identity
switches, fragmentation, correct gap reconnection, and the fraction of each
trajectory recovered correctly. Also measure manual correction effort, runtime,
and memory as crowding increases. Report difficult encounters separately rather
than letting easy isolated cells dominate the result.

CTC provides detection, segmentation, tracking, and biologically motivated
metrics, but its datasets and rankings do not establish performance on these
tissue experiments. Evaluate motion, temporal optimization, Z evidence, and
segmentation repair separately before combining them.

Avoid initially favoring motion toward the chemoattractant source: imposing that
direction could bias the migration measurements the experiment aims to obtain.

## Research references

- [Baxter Algorithms, ctc2024](https://github.com/klasma/BaxterAlgorithms/tree/ctc2024):
  priority source for the tracking-only port, including the 2024 update.
- [Baxter CTC participant page](https://celltrackingchallenge.net/participants/kth-se/):
  identifies the 2024 linking-only submission and its source branch.
- [Baxter compilation script (master)](https://github.com/klasma/BaxterAlgorithms/blob/master/CompileMex.m):
  confirms C++ implementations including Viterbi tracking and Hungarian matching;
  the selected 2024 branch still needs its own dependency audit.
- [pybind11](https://pybind11.readthedocs.io/en/stable/): potential Python interface
  for the retained C++ engine.
- [Trackastra paper](https://arxiv.org/abs/2405.15700): pretrained association
  prediction over a temporal window, followed by linking of segmented objects.
- [EmbedTrack](https://github.com/kaloeffler/EmbedTrack): learned joint segmentation
  and inter-frame displacement. Pretrained models exist; transfer to tissue
  experiments needs evaluation.
- [BiologicalNeeds](https://github.com/TimoK93/BiologicalNeeds): extends EmbedTrack
  with uncertainty estimates and multiple tracking hypotheses. Its released
  pipeline consumes EmbedTrack-derived outputs; it is not a drop-in Trackastra
  replacement.
- [KIT-GE graph-based tracking paper](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0249257):
  local motion estimation, coupled minimum-cost-flow tracking, and segmentation
  error correction without training the tracker. It assumes most initial masks
  represent individual cells reasonably well.
- [Classical optical flow in scikit-image](https://scikit-image.org/docs/stable/auto_examples/registration/plot_opticalflow.html):
  implementations for estimating image displacement without neural-network training.
- [Linear assignment in SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html):
  an available assignment solver; SciPy uses a modified Jonker–Volgenant algorithm.
- [Cell Tracking Challenge evaluation](https://celltrackingchallenge.net/evaluation-methodology/):
  separate measures for detection, segmentation, tracking, and biological usefulness.
