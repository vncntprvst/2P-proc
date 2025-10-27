# Analysis 2P Modules

This directory contains modular components for the Analysis 2P pipeline.

## Core Modules

### Motion Correction (`motion_correction.py`)

A comprehensive workflow module for motion correction in 2-photon calcium imaging data.

**Key Features:**
- Raw data concatenation
- Motion correction using CaImAn/Mesmerize
- Z-motion correction (optional)
- Memory optimization and garbage collection
- Movie output generation
- Movie format conversion and optimization

**Usage:**
```python
from modules.motion_correction import run_motion_correction_workflow

# Define parameters
parameters = {
    'params_mcorr': {
        'main': {
            'strides': [36, 36],
            'overlaps': [24, 24],
            'max_shifts': [12, 12],
            'max_deviation_rigid': 6,
            'border_nan': 'copy',
            'pw_rigid': True,
            'gSig_filt': None
        }
    }
}

# Run the workflow
results = run_motion_correction_workflow(
    data_path=['/path/to/data1', '/path/to/data2'],
    export_path='/path/to/output',
    parameters=parameters,
    regex_pattern='*_Ch2_*.ome.tif',
    recompute=False,
    create_movies=True
)
```

### Bruker TIF Concatenation (`bruker_concat_tif.py`)

Functions for concatenating Bruker microscopy files into a single multi-page TIFF file.

### Z-Motion Correction (`compute_zcorr.py`)

Functions for correcting Z-motion in 2-photon imaging data.

## Testing

Run tests using the test scripts in the `tests` directory:

```bash
python tests/test_motion_correction.py
```

## Requirements

- Python 3.7+
- CaImAn
- Mesmerize-core
- NumPy
- Pillow (for TIFF handling)
