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

### Default GPU setup

Plain `uv sync` and `uv run` select the development defaults automatically:

- Windows x64 uses PyTorch 2.10.0 and torchvision 0.25.0 with CUDA 12.6,
  verified on the GTX 1080 with NVIDIA driver 576.52.
- Linux keeps its existing PyTorch package source and locked versions. GPU
  support there depends on the Linux machine's GPU and driver; it has not been
  tested from this Windows machine.

No extra flags are needed for everyday development:

```bash
uv run fits-gui
uv run fits-viewer --tool segmentation
uv run cellpose
```

The shared default is `[tool.uv].default-groups = ["dev", "cuda126"]` in
`pyproject.toml`. The accelerator groups only affect Windows x64. The `cpu`
and `cuda128` groups remain available for future machines; to temporarily
select one, disable the default accelerator group:

```bash
uv sync --no-group cuda126 --group cpu
uv run --no-group cuda126 --group cpu fits-gui
```

Replace `cpu` with `cuda128` for CUDA 12.8 on compatible hardware. A later
plain `uv sync` or `uv run` restores the shared default. These groups are
mutually exclusive, so do not use `--all-groups`. The former `--extra` GPU
profiles have been replaced by dependency groups.

CUDA 12.6 retains support for the GTX 1080 (Pascal); the CUDA 12.8 build does
not. See [PyTorch's architecture compatibility notice](https://github.com/pytorch/pytorch/issues/157517).
A separate CUDA toolkit installation is not needed.

Check GPU availability from the FITS directory:

```bash
uv run python -c "import torch; from cellpose import core; print(torch.__version__, torch.version.cuda); print('Cellpose GPU:', core.use_gpu())"
```

Restart running Python sessions after changing PyTorch, and enable `use GPU`
in the Cellpose GUI (or pass `--use_gpu` to the Cellpose CLI).

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
