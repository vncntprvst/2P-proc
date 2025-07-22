"""
Analysis 2P Pipeline modules

This package contains core modules for the Analysis 2P pipeline:
- bruker_concat_tif: Functions to concatenate Bruker microscopy files
- compute_zcorr: Functions for Z-motion correction
- motion_correction: Complete motion correction workflow
"""

# Import modules to make them available directly from the package
from . import bruker_concat_tif
from . import compute_zcorr
from . import motion_correction
