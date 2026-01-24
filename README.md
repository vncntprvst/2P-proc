# 2P-proc (spin-top)

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![CaImAn Version](https://img.shields.io/badge/CaImAn-1.12.2+-green)](https://github.com/flatironinstitute/CaImAn)
![License](https://img.shields.io/badge/license-MIT-red)

**2P-proc (spin-top)** is a 2-photon calcium imaging data processing pipeline built on [CaImAn](https://github.com/flatironinstitute/CaImAn/) and [Mesmerize](https://github.com/nel-lab/mesmerize-core/).

This package provides:
- **Motion correction**: Rigid and non-rigid motion correction with optional z-drift correction
- **ROI extraction**: CNMF-based and Suite2p-based cell detection and segmentation
- **Spike deconvolution**: Temporal activity inference from calcium signals
- **Parameter optimization**: Notebooks for systematic parameter exploration
- **Multi-session registration**: Cross-session ROI alignment using CaImAn's registration algorithm

## Installation

### Option 1: Install from GitHub (recommended)

```bash
# Create and activate conda environment with CaImAn
conda create -n toupie python=3.9 -c conda-forge
conda activate toupie
conda install -c conda-forge caiman mesmerize-core
caimanmanager install

# Install spin-top
pip install git+https://github.com/vncntprvst/2P-proc.git
```

### Option 2: Development install

```bash
# Clone repository
git clone https://github.com/vncntprvst/2P-proc.git
cd 2P-proc

# Create and activate environment
conda create -n toupie python=3.9 -c conda-forge
conda activate toupie
conda install -c conda-forge caiman mesmerize-core
caimanmanager install

# Install in editable mode
pip install -e .

# Optional: install visualization and Suite2p support
pip install -e ".[viz,suite2p]"
```

### Additional dependencies

For z-correction:
```bash
conda install -c conda-forge mkl mkl_fft
pip install suite2p
```

For visualization:
```bash
pip install "fastplotlib[notebook]"
pip install plotly
```

## Quick Start

### 1. Configure your pipeline

Create a configuration JSON based on `pipeline/configs/config_template.json`:

```json
{
  "acquisition": {
    "fps": 30.0,
    "pixel_size": 0.65,
    "num_planes": 1
  },
  "motion_correction": {
    "max_shifts": [6, 6],
    "strides": [48, 48],
    "overlaps": [24, 24]
  },
  "cnmf": {
    "gSig": [4, 4],
    "K": 100,
    "p": 1
  },
  "paths": {
    "input_movie": "/path/to/data.tif",
    "output_dir": "/path/to/output/"
  }
}
```

### 2. Run the pipeline

**On a local machine:**

```bash
python pipeline/pipeline_mcorr.py configs/my_config.json
python pipeline/pipeline_cnmf.py configs/my_config.json
python pipeline/roi_zcorr.py configs/my_config.json  # optional z-correction
```

**On a cluster with SLURM:**

```bash
sbatch scripts/batch_2P_pipeline.sh configs/my_config.json
```

### 3. Multi-session registration

```bash
python Caiman/multisession_registration.py --json configs/my_config.json
```

## Pipeline Components

### Motion Correction
- Rigid and non-rigid motion correction using NoRMCorre algorithm
- Optional z-drift correction using anatomical z-stack
- Export to multiple formats (TIFF, memmap, HDF5)

### CNMF Extraction
- Constrained non-negative matrix factorization for ROI detection
- Automatic component quality assessment
- Denoised fluorescence traces and deconvolved spikes

### ROI Z-Correction
- Regress and subtract axial drift from ROI traces
- Compatible with both CaImAn and Suite2p outputs
- Preserves temporal dynamics while correcting for z-motion

### Parameter Optimization
Jupyter notebooks in `Mesmerize/` for systematic parameter exploration:
- `optimize_mcorr_bruker.ipynb`: Motion correction parameters
- `optimize_cnmf_bruker.ipynb`: CNMF extraction parameters
- `pipeline_notebook_template.ipynb`: Complete pipeline template

## Testing

```bash
# Download test data (~1.2GB)
./scripts/download_test_data.sh

# Run motion correction test
./scripts/run_motion_correction_test.sh

# Run full test suite
pytest tests/
```

## Container Support

Docker/Singularity containers are available for cluster computing:
- `containers/analysis_2p`: Main processing container with spin-top installed
- `containers/suite2p`: Suite2p-based extraction pipeline
- `containers/allenneuraldynamics`: Integration with AIND extraction capsule

Build and use containers:
```bash
# Build container
cd containers/analysis_2p
docker build -t spin-top:latest .

# Run with Singularity
singularity exec containers/analysis-2p_latest.sif python pipeline/pipeline_mcorr.py config.json
```

## Documentation

- **Configuration**: See `pipeline/configs/config_template.json` for all available parameters
- **API Reference**: Coming soon
- **Tutorials**: Jupyter notebooks in `Mesmerize/` and `Caiman/`

## Post-Processing and Analysis

For post-processing analysis (behavior integration, population analysis, etc.), see the companion repository:
**[Analysis 2P](https://github.com/pseudomanu/Analysis_2P)** - Matlab-based analysis pipeline with DeepLabCut and Rastermap integration

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## Citation

If you use this software, please cite:
- CaImAn: Giovannucci et al. (2019) eLife
- Mesmerize: Corder et al. (2024)

## License

This project is licensed under the MIT License - see [LICENSE.md](LICENSE.md) for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/vncntprvst/2P-proc/issues)
- **Discussions**: [GitHub Discussions](https://github.com/vncntprvst/2P-proc/discussions)
