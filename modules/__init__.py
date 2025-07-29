"""
Analysis 2P Pipeline modules

This package contains core modules for the Analysis 2P pipeline:
- bruker_concat_tif: Functions to concatenate Bruker microscopy files
- motion_correction: Complete motion correction workflow
- compute_zcorr: Functions for Z-motion correction
- extraction: Functions for extracting ROIs and traces from 2P data
"""

from __future__ import annotations

# import warnings
# from pathlib import Path

# Version information
__version__ = "1.0.0"
__author__ = "Manuel Levy, Vincent Prevosto"

# # Check core dependencies at import time
# def _check_dependencies():
#     """Validate core dependencies are available"""
#     required = ['numpy', 'scipy']
#     missing = []
    
#     for dep in required:
#         try:
#             __import__(dep)
#         except ImportError:
#             missing.append(dep)
    
#     if missing:
#         raise ImportError(
#             f"Missing required dependencies: {missing}. "
#             f"Install with: conda install {' '.join(missing)}"
#         )

# _check_dependencies()

# Import core modules
from . import bruker_concat_tif
from . import compute_zcorr
from . import motion_correction
from . import extraction  

# # Expose key functions at package level
# from .motion_correction import run_motion_correction_workflow
# from .extraction import run_cnmf
# from .compute_zcorr import compute_zcorrel, subtract_z_motion_patches

# # Define what gets imported with "from modules import *"
# __all__ = [
#     'motion_correction',
#     'extraction', 
#     'compute_zcorr',
#     'bruker_concat_tif',
#     'run_motion_correction_workflow',
#     'run_cnmf',
#     'compute_zcorrel',
#     'subtract_z_motion_patches'
# ]