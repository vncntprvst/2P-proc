# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**optimouse** (PyPI: `optimouse`) is a two-photon calcium imaging processing pipeline for neuroscience. It chains motion correction → ROI extraction → multi-session registration with support for both CaImAn/CNMF and Suite2p as extraction backends. The Streamlit UI (`ui/ui_app.py`) lets users build and submit configs without touching the CLI.

## Development Setup

```bash
# Install in editable mode (core dependencies)
pip install -e .

# Also install dev tools
pip install -e ".[dev]"

# CaImAn must be installed separately
pip install "git+https://github.com/flatironinstitute/CaImAn.git@v1.12.2"
caimanmanager install
```

Environment setup scripts for isolated venvs are in `environments/`.

## Common Commands

```bash
# Format code (line-length 100)
black .

# Lint
ruff check .
ruff check --fix .

# Run full test suite (requires ~1.2 GB of test data first)
./scripts/download_test_data.sh
pytest tests/

# Run a single test file
pytest tests/test_motion_correction.py

# Run the web UI
streamlit run ui/ui_app.py
```

> **Note:** CI workflows are disabled (`.github/workflows.disabled/`). Tests in `tests/` are flagged in the README as potentially outdated relative to the current pipeline.

## Running the Pipeline

The pipeline runs in sequential phases via CLI modules:

```bash
# Phase 1: Motion correction
python -m pipeline.pipeline_mcorr path/to/config.json

# Phase 2: ROI extraction (CNMF or Suite2p)
python -m pipeline.pipeline_cnmf path/to/config.json

# Phase 3: Multi-session registration
python Caiman/multisession_registration.py --json path/to/config.json

# SLURM batch submission
cp scripts/2P_proc_template.sh scripts/2P_proc.sh
sbatch scripts/2P_proc.sh path/to/config.json
```

Container images are on Docker Hub (`wanglabneuro/2p_proc`); Singularity definitions are in `containers/`.

## Architecture

### Processing Flow

```
Raw TIFF/HDF5 → Motion Correction (NoRMCorre) → ROI Extraction (CNMF or Suite2p) → Deconvolution → Multi-session Registration
```

### Module Roles

| File | Role |
|---|---|
| `pipeline/pipeline_mcorr.py` | Entry point for motion correction; delegates to `modules/motion_correction.py` |
| `pipeline/pipeline_cnmf.py` | Entry point for extraction; delegates to `modules/extraction.py` |
| `modules/motion_correction.py` | Full motion correction workflow via CaImAn/NoRMCorre |
| `modules/extraction.py` | CNMF and Suite2p extraction; exports to MAT/NWB/memmap |
| `modules/compute_zcorr.py` | Z-drift detection and correction (largest module, ~90 KB) |
| `modules/bruker_concat_tif.py` | Concatenates multi-file Bruker TIFF sessions before processing |
| `pipeline/utils/config_loader.py` | JSON config parsing with `${VAR}` substitution and `__include` directives |
| `pipeline/utils/pipeline_utils.py` | Shared utilities: memory management, file I/O, logging |
| `Caiman/multisession_registration.py` | Cross-session cell alignment using CaImAn |
| `ui/ui_app.py` | Streamlit UI for building configs and submitting jobs (~45 KB) |

### Configuration System

Configs are JSON files with three special features:
1. **`_env` block** — define reusable path variables referenced as `${VAR}` anywhere in the file
2. **`__include` directive** — merge another JSON snippet into the current object
3. **Variable substitution** — `${VAR}` expands at load time via `config_loader.py`

Templates: `pipeline/configs/config_template_cnmf.json` and `config_template_suite2p.json`.

### Backend Switching (CNMF vs Suite2p)

The extraction module selects the backend from the config key `extraction_method`. A key bridging class is `CaimanMemmapBinary` in `modules/extraction.py`, which wraps CaImAn's memmap format to satisfy Suite2p's `BinaryFile` API — this is the main integration point between the two ecosystems.

### GPU / TensorFlow

The pipeline explicitly sets TF environment variables at startup (`TF_CPP_MIN_LOG_LEVEL`, `CUDA_VISIBLE_DEVICES`, `TF_FORCE_GPU_ALLOW_GROWTH`). CaImAn motion correction uses GPU when available; Suite2p uses PyTorch.

## Code Style

- **Black**, line length 100, targets Python 3.10–3.11
- **Ruff** linter, same line length, target `py310`
- No type annotations are enforced; existing code is largely unannotated
