# Software credits and citation guidance

[Developer documentation](README.md) · [Project README](../../README.md#citations-and-acknowledgments)

FITS combines independently maintained scientific libraries with its own workflow
and companion packages. Credit the upstream methods actually used in your
analysis, including the relevant model/version. Record your FITS version and
settings alongside those citations.

## Scientific methods, readers, and models

| Software | Role in FITS | Citation or upstream guidance |
| --- | --- | --- |
| [Cellpose](https://github.com/MouseLand/cellpose) | Segmentation and model-dependent restoration through Cellpose Kit. | [Model-specific citation instructions](https://github.com/MouseLand/cellpose#citation). Cellpose 1–3, restoration, and Cellpose-SAM have different relevant papers. |
| [nd2](https://github.com/tlambert03/nd2) | Nikon ND2 image and metadata reading through scope_io. | Acknowledge the nd2 project and the version used; consult its repository for current software citation metadata. |
| [tifffile](https://github.com/cgohlke/tifffile) | TIFF image/metadata storage through scope_io. | Use the project's software citation guidance. |
| [imagecodecs](https://github.com/cgohlke/imagecodecs) | Image compression/decompression. | Use the project's software citation guidance. |
| [roifile](https://github.com/cgohlke/roifile) | ImageJ ROI and overlay serialization. | Use the project's software citation guidance. |
| [SMO](https://github.com/maurosilber/SMO) | Silver Mountain Operator background estimation through bg_sub. | Cite the [peer-reviewed article](https://doi.org/10.1364/JOSAA.477468), as requested by the [SMO authors](https://github.com/maurosilber/SMO#citation). |
| [pyStackReg](https://github.com/glichtner/pystackreg) | Registration through stackalign. | Credit Gregor Lichtner's Python port and Philippe Thévenaz's TurboReg/StackReg work. The upstream reference is Thévenaz, Ruttimann and Unser, *A Pyramid Approach to Subpixel Registration Based on Intensity* (1998), linked from the [pyStackReg project](https://github.com/glichtner/pystackreg#author-information). |
| [OpenCV](https://opencv.org/) | Registration and geometric image transforms through stackalign. | Follow the project's software citation guidance. |
| [scikit-image](https://scikit-image.org/) | Image processing, registration, and object measurements. | See [scikit-image citation guidance](https://scikit-image.org/docs/stable/about.html#citing-scikit-image). |
| [Trackastra](https://github.com/weigertlab/trackastra) | Linking cells across frames through tracklink. | Gallusser and Weigert, [*Trackastra: Transformer-based cell tracking for live-cell microscopy*](https://arxiv.org/abs/2405.15700) (2024). |
| [µSAM](https://github.com/computational-cell-analytics/micro-sam) | Prompt-based Add/Edit prediction through the FITS headless integration. | [*Segment Anything for Microscopy*](https://doi.org/10.1038/s41592-024-02580-4) (2025) and the upstream [citation instructions](https://github.com/computational-cell-analytics/micro-sam#citation). |
| [Segment Anything](https://github.com/facebookresearch/segment-anything) | Foundation model used by the µSAM integration. | [*Segment Anything*](https://arxiv.org/abs/2304.02643) (2023); follow µSAM's guidance for the model used. |
| [MobileSAM](https://github.com/ChaoningZhang/MobileSAM) | Lightweight SAM model option. | [MobileSAM paper](https://arxiv.org/abs/2306.14289) when using the corresponding model. |

## Numerical, table, and application foundations

These projects support FITS directly or through its companion libraries. Their
names are acknowledgments, not a claim that every package needs a separate
method citation for every analysis. Follow applicable upstream citation requests.

| Projects | Contribution |
| --- | --- |
| [NumPy](https://numpy.org/), [SciPy](https://scipy.org/) | Arrays and numerical/scientific operations. |
| [pandas](https://pandas.pydata.org/), [PyArrow](https://arrow.apache.org/docs/python/) | Measurement tables and Parquet files. |
| [PyTorch](https://pytorch.org/), [torchvision](https://github.com/pytorch/vision), [timm](https://github.com/huggingface/pytorch-image-models) | Model execution and vision components used by the inference libraries. |
| [joblib](https://joblib.readthedocs.io/) | Parallel numerical work in bioimagequant. |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/), [pyqtgraph](https://www.pyqtgraph.org/) | Desktop GUI and image visualization. |
| [Pydantic](https://docs.pydantic.dev/), [Typer](https://typer.tiangolo.com/), [tomlkit](https://github.com/python-poetry/tomlkit) | Settings validation, command-line tools, and TOML preservation. |
| [Rich](https://github.com/Textualize/rich), [tqdm](https://github.com/tqdm/tqdm), [IPython](https://ipython.org/) | Progress displays and interactive Python support. |
| [filelock](https://github.com/tox-dev/filelock), [psutil](https://github.com/giampaolo/psutil), [packaging](https://packaging.pypa.io/) | Process coordination, process inspection, and version handling. |
| [bioimage-cpp](https://pypi.org/project/bioimage-cpp/), [pooch](https://www.fatiando.org/pooch/), [xxhash](https://github.com/ifduyue/python-xxhash), [Zarr](https://zarr.dev/) | Additional declared dependencies of the headless µSAM integration. |

Exact dependency versions and further transitive dependencies are recorded in
[`uv.lock`](../../uv.lock). This page highlights the libraries declared by FITS,
its companion packages, and the headless µSAM integration; it is not an inventory
of every transitive package.

## Installation and optional tools

- [uv](https://github.com/astral-sh/uv): Python/environment installation and dependency management.
- [Git](https://git-scm.com/): source checkout, submodules, and updates.
- [Tad](https://www.tadviewer.com/): optional independent Parquet table viewer.
- [Data Wrangler for Visual Studio Code](https://marketplace.visualstudio.com/items?itemName=ms-toolsai.datawrangler): separately installed table-viewing alternative.

## FITS companion repositories

These libraries provide the FITS-facing integration or numerical responsibilities
and are maintained as separate repositories:

- [scope_io](https://github.com/BennyGinger/scope_io): microscopy I/O and metadata.
- [Cellpose Kit](https://github.com/BennyGinger/Cellpose-kit): Cellpose integration.
- [stackalign](https://github.com/BennyGinger/stackalign): registration interface.
- [bg_sub](https://github.com/BennyGinger/bg_sub): background-subtraction interface.
- [tracklink](https://github.com/BennyGinger/tracklink): tracking integration.
- [mask_interpolation](https://github.com/BennyGinger/mask_interpolation): sparse-mask interpolation.
- [bioimagequant](https://github.com/BennyGinger/bioimagequant): quantitative analysis.
- [progress_bar](https://github.com/BennyGinger/Progress_bar): workflow progress reporting.
- [micro-sam-headless](https://github.com/BennyGinger/micro-sam-headless): the FITS headless fork of upstream µSAM.
