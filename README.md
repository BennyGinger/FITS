# FITS

FITS—Fluorescent Image Tracking Software—is a reproducible workflow for
processing and quantifying fluorescence-microscopy experiments. It brings image
conversion, registration, background subtraction, segmentation, tracking,
spatial profiling, and labeled-region extraction into one experiment-aware
pipeline.

The project is aimed at researchers who should not need to write Python to run
an analysis. Its desktop interface exposes pipeline settings and dedicated
viewers for segmentation tuning, reference masks, and ROI masks, while the CLI
supports scripted and repeatable runs. Both use the same settings models and
workflow engine.

## Design

FITS owns experiment discovery, scheduling, state, paths, provenance, and saved
artifacts. Numerical work is delegated to focused submodules that accept arrays
and can also be used independently:

- `fits_io` reads microscopy formats and writes metadata-rich FITS TIFFs.
- `stackalign` performs time-wise and cross-channel registration.
- `bg_sub` removes spatially varying image background.
- `cellpose_kit` provides a stable Cellpose v3/v4 segmentation interface.
- `tracklink` links segmented objects over time.
- `mask_interpolation` completes sparsely drawn reference and ROI masks.
- `bioimagequant` performs object extraction and distance-profile analysis.
- `progress_bar` provides terminal progress and controlled log display.

## Development setup

Clone the repository together with its submodules, then synchronize the uv
workspace:

```bash
git clone --recurse-submodules https://github.com/BennyGinger/FITS.git fits
cd fits
uv sync
```

Launch the main settings interface with `uv run fits-gui`, or open the image
tools directly:

```bash
uv run fits-viewer --tool segmentation
uv run fits-viewer --tool binary
uv run fits-viewer --tool all
```

The command-line interface is available through `uv run fits --help`.

## Repository maintenance

FITS uses Git submodules and a uv workspace. The practical commands for
cloning, updating, editing, adding, and removing submodules are collected in
the [Git and submodule cheatsheet](docs/git_cheatsheet.md).
