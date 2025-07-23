import types, sys

# Provide a minimal stub for caiman.mmapping.load_memmap so that modules.compute_zcorr imports
caiman_mod = types.ModuleType('caiman')
mmapping_mod = types.ModuleType('caiman.mmapping')
mmapping_mod.load_memmap = lambda *a, **k: None
caiman_mod.mmapping = mmapping_mod
sys.modules.setdefault('caiman', caiman_mod)
sys.modules.setdefault('caiman.mmapping', mmapping_mod)

import numpy as np
import pandas as pd
from modules.compute_zcorr import make_composite_f_anat


def test_make_composite_f_anat_resizes_patch():
    # Labeled zones with one zone occupying a 5x5 area
    labeled_zones = np.zeros((6, 6), dtype=int)
    labeled_zones[:5, :5] = 1

    # Patch is only 3x3 but covers part of the zone
    patch = np.ones((3, 3), dtype=np.float32)

    patch_correlations = pd.DataFrame([
        {
            'frame_num': 0,
            'patch_number': 0,
            'patch_z_pos': 0,
            'r_squared': 1.0,
            'patch_x_lims': [0, 3],
            'patch_y_lims': [0, 3],
            'Z_patch': patch,
        }
    ])

    F_anat, zone_df = make_composite_f_anat(patch_correlations, labeled_zones)

    # Output should have the same spatial dimensions as labeled_zones
    assert F_anat.shape == (1, 6, 6)
    # The patch should have been resized to fill the 5x5 zone
    assert np.allclose(F_anat[0, :5, :5], 1.0)
    # Outside the zone should remain zero
    assert np.allclose(F_anat[0, 5, :], 0)
    assert np.allclose(F_anat[0, :, 5], 0)
