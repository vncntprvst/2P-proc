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

# Core modules are imported on first use (``modules.compute_zcorr`` or
# ``from modules import compute_zcorr``), so lightweight modules such as
# cell_registration can be used without the CaImAn / Mesmerize stack.
_LAZY = ("bruker_concat_tif", "compute_zcorr", "motion_correction", "extraction")


def __getattr__(name):
    if name in _LAZY:
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
