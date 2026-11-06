# Legacy BaxTrack integration: retrieval context

This note records a read-only inspection of the old Python/Docker integration.
Use it alongside [the future tracking plan](motion_assisted_tracking.md).
It describes historical code, not a supported installation procedure.

## Source snapshot

- Repository: `/home/ben/Lab/Python/ImageAnalysis_pipeline`
- Commit: `3792771f67e78e87b7ea41f7d2c68d066aa7051e`
- Date: 2023-06-21
- Message: `Add BaxTrack for installation in docker`
- The commit adds four deployment-package files, including `BaxTrack.ctf`
  (419,085 bytes). The Dockerfile and Python integration already exist in this
  snapshot; they were not all introduced by this commit.
- Historical Python sources are under `pipeline/`, not the current
  `imageanalysis/tracking/` layout.

Retrieve files without checking out or changing the old worktree:

```bash
git -C /home/ben/Lab/Python/ImageAnalysis_pipeline show 3792771f67e78e87b7ea41f7d2c68d066aa7051e:pipeline/experiments.py
git -C /home/ben/Lab/Python/ImageAnalysis_pipeline show 3792771f67e78e87b7ea41f7d2c68d066aa7051e:pipeline/core.py
git -C /home/ben/Lab/Python/ImageAnalysis_pipeline show 3792771f67e78e87b7ea41f7d2c68d066aa7051e:Dockerfile
```

## Code map at this commit

| Historical file | Relevant entry point or content |
| --- | --- |
| `pipeline/core.py:219` | `Experiments.exp_bax_track`: initializes and reuses the deployed runtime handle; loops over experiments. |
| `pipeline/experiments.py:105` | `Exp_Indiv.baxter_tracking`: stages files, invokes tracking, imports results, saves metadata. |
| `pipeline/experiments.py:492` | `get_bax_settings`: complete historical settings and 2D/3D selection. |
| `pipeline/utility.py:598` | `save_mask`: per-frame/per-Z TIFF naming and `uint16` output. |
| `pipeline/utility.py:670` | `get_pos_cell` and `trim_mask`: optional filtering to full-duration tracks. |
| `Dockerfile`, `environment.yml`, `install` | Container dependencies and manual installation instructions. |
| `for_redistribution_files_only/BaxTrack/__init__.py` | Generated MathWorks loader, runtime discovery and initialization. |
| `for_redistribution_files_only/BaxTrack/BaxTrack.ctf` | Deployed MATLAB package; not the Python tracking algorithm source. |
| `for_redistribution_files_only/setup.py`, `GettingStarted.html` | Generated installation metadata and Compiler SDK instructions. |

## Recovered tracking contract

The workflow segments with Cellpose first, saving masks under `Masks_CP`.
The Python-to-MATLAB boundary is file-based, rather than a direct NumPy array
argument. Python selects a channel and copies its mask TIFFs into an experiment
subdirectory named `.Baxtrack_temp`. It creates `Setting.csv`, then invokes:

```python
import BaxTrack as BTP
handle = BTP.initialize()  # cached as Experiments.track
handle.PythonTracking(track_cores, tempFolder, img_path, tempFolder, csv_path)
```

The positional arguments in the call are worker count (default 6), staged-mask
folder, image folder, output folder (same temporary folder), and settings CSV.
These roles are inferred from the caller; `PythonTracking.m` is not present in
the snapshot. Images come from `Images` or `Images_Registered` unless overridden.

After tracking, Python reads newly produced mask TIFFs, optionally trims tracks,
and saves `Masks_BaxTracked/mask_<channel>_f0001_z0001.tif`-style files. It copies
`res_track.txt` and records settings in `exp_properties.pickle`, then removes the
temporary directory. Existing channel output skips processing unless overwritten.

The optional `trim` flag keeps IDs whose track-table start is 0 and end is
`frames - 1`; it is not a general short-gap repair policy. The parser names the
fourth table column `isPos` but does not use it here; verify upstream semantics
instead of adopting that name in the new data model.

## Historical settings worth recovering

- `SegAlgorithm='Segment_import'`: confirms externally segmented masks are used.
- `numZ` comes from experiment metadata. For one plane, the wrapper selects
  `MigLogLikeList_uniformClutter` and sets `TrackZSpeedStd='EMPTY'`. For multiple
  planes it selects `MigLogLikeList_3D`.
- Defaults include `TrackXSpeedStd=12`, `TrackZSpeedStd=3`,
  `TrackNumNeighbours=3`, `TrackBipartiteMatch=1`, `TrackFalsePos=1`, and
  `TrackMergeWatersheds=1`.
- Count/event parameters include `pCnt0=0.2`, `pCnt1=0.7`, `pCnt2=0.1`,
  `pCntExtrap=0.25`, `pSplit=0`, `pDeath=0`, and appearance/disappearance values
  of `0.001`.
- The dictionary also defaults to `pixelSize=0.65` and `dT=0`. These are
  historical defaults, not measured calibration for future experiments.
- Recognized keyword arguments override defaults, then the wrapper enforces its
  dimensionality-dependent settings and stringifies all values for CSV export.

The old docstring calls the speed parameters maximum displacements. Their names
suggest standard deviations; check upstream definitions and units before reuse.
The 3D branch is concrete evidence of the integration selecting depth-aware
scoring, but this snapshot does not reveal the implementation of that scoring.

## Deployment constraints and unknowns

The active Dockerfile uses Ubuntu 20.04 with CUDA 11.3.1, Conda Python 3.8,
PyTorch 1.11.0, and MATLAB Runtime R2022a Update 6 installed under `/opt/mcr`.
It installs the generated BaxTrack package with `python setup.py install`.
The loader expects runtime 9.12 and explicitly accepts only Python 2.7, 3.8,
or 3.9. It discovers runtime libraries through platform-specific environment
variables and imports MathWorks runtime extensions. This is not a standalone
Python binding to Baxter's C++ engine.

The Dockerfile creates a `matlab_shell.sh` helper containing library paths,
but does not establish its invocation as an entry point. The manual `install`
file separately describes exporting runtime library paths. Mixed pinned and
unpinned packages, the runtime/Python version coupling, CUDA, and GUI dependencies
are visible portability concerns; no historical installation failure was
reproduced during this inspection.

No Gurobi reference was found in tracked text at this commit. The user reports
Gurobi and annual academic-license renewal in the previous workflow; its location
in the deployed package or another installation step remains unverified. Do not
conclude either that the C++ linker requires it or that the old deployment did not.

The snapshot contains no `.m`, `.cpp`, or `.h` source files. The CTF was not
unpacked or executed. It cannot establish the exact upstream Baxter revision,
custom MATLAB wrapper implementation, or correspondence with the 2024 update.
This 2023 deployment predates that update.

## Implications for the planned port

Use this snapshot to recover the input/output contract and previous settings.
Obtain the tracking implementation from Baxter's upstream `ctc2024` branch,
including its required preparation/scoring code, and audit dependencies there.
Preserve supported 3D behavior and initially accept Cellpose segmentation.

The target remains Python plus reusable C++, without mandatory MATLAB Runtime
or Gurobi. Original MATLAB comparison is optional: use any surviving compatible
results, annotated clips, and independently checkable synthetic cases. Exact
historical equivalence remains unverified without reference outputs.

Useful additional history: commit
`9f02793085a42f93307a22f6ba263ab825c8b4e3` (2024-03-12, `Remove BaxTrack`)
removes the tracking methods from `pipeline/core.py` and `pipeline/experiments.py`.
