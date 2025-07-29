"""
Analysis 2P Pipeline modules

This package contains core modules for the Analysis 2P pipeline:
- bruker_concat_tif: Functions to concatenate Bruker microscopy files
- motion_correction: Complete motion correction workflow
- compute_zcorr: Functions for Z-motion correction
- extraction: Functions for extracting ROIs and traces from 2P data
"""

# Import modules to make them available directly from the package
from . import bruker_concat_tif
from . import compute_zcorr
# from . import motion_correction
# from . import extraction
