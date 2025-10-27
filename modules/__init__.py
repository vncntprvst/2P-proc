"""
Analysis 2P Pipeline modules

This package contains core modules for the Analysis 2P pipeline:
- bruker_concat_tif: Functions to concatenate Bruker microscopy files
- motion_correction: Complete motion correction workflow
- compute_zcorr: Functions for Z-motion correction
- extraction: Functions for extracting ROIs and traces from 2P data
"""

from __future__ import annotations

# Version information
__version__ = "1.1.0"
__author__ = "Manuel Levy, Vincent Prevosto"

# Import core modules
from . import bruker_concat_tif
from . import compute_zcorr
from . import motion_correction
from . import extraction  
