from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import tifffile
from scipy.stats import mode
from sklearn.linear_model import HuberRegressor
from caiman.source_extraction.cnmf.cnmf import CNMF

from pipeline.utils.pipeline_utils import log_and_print, memory_manager


def run_roi_zcorr(export_path, parameters):
    """Correct ROI fluorescence traces for z-motion artifacts.

    Parameters
    ----------
    export_path : str or Path
        Directory containing CNMF outputs and z-motion files.
    parameters : dict
        Dictionary with processing parameters (unused, reserved for future use).
    """

    export_path = Path(export_path)
    log_and_print("Starting ROI z-motion correction.")

    cnmf_file = export_path / "cnmf_result.hdf5"
    zcorr_file = export_path / "z_correlation.npz"
    f_anat_files = sorted(export_path.glob("F_anat_non_rigid*.tiff"))

    if not cnmf_file.exists() or not zcorr_file.exists() or not f_anat_files:
        log_and_print(
            "Required files for ROI z-motion correction missing. Skipping.",
            level="warning",
        )
        return None

    with memory_manager("roi z-motion correction"):
        zpos = np.load(zcorr_file)["zpos"]
        f_anat_movie = tifffile.imread(str(f_anat_files[0]))
        # tifffile returns (T, Y, X); transpose to (Y, X, T)
        if f_anat_movie.shape[0] == zpos.shape[0]:
            f_anat_movie = np.transpose(f_anat_movie, (1, 2, 0))

        cnm = CNMF()
        cnm.load(str(cnmf_file))
        F = cnm.estimates.F
        A = cnm.estimates.A.tocsc()
        d1 = cnm.estimates.d1
        d2 = cnm.estimates.d2
        n_neuron, n_frame = F.shape

        Fz = np.zeros((n_neuron, n_frame))
        Fz_rescaled = np.zeros_like(F)
        Fcorrected = np.zeros_like(F)
        b = np.zeros(n_neuron)

        for i in range(n_neuron):
            ind = A[:, i].nonzero()[0]
            y, x = np.unravel_index(ind, (d1, d2))
            weights = np.full(len(x), 1 / len(x))
            for w, yy, xx in zip(weights, y, x):
                Fz[i] += w * f_anat_movie[yy, xx, :]
            F0 = F[i].mean()
            Fz0 = Fz[i].mean()
            huber = HuberRegressor(fit_intercept=False)
            huber.fit((Fz[i] - Fz0).reshape(-1, 1), F[i] - F0)
            b[i] = huber.coef_[0]
            Fz_rescaled[i] = b[i] * (Fz[i] - Fz0)
            Fcorrected[i] = F[i] - Fz_rescaled[i]

        z_mode = mode(zpos, keepdims=False).mode
        if np.ndim(z_mode) > 0:
            z_mode = z_mode[0]
        missing = np.abs(zpos - z_mode) > 5
        if np.any(missing):
            Fcorrected[:, missing] = np.nan
            Fcorrected = (
                pd.DataFrame(Fcorrected)
                .interpolate(method="linear", axis=1, limit_direction="both")
                .to_numpy()
            )

        np.save(export_path / "F_roi_zcorrected.npy", Fcorrected)
        np.save(export_path / "F_roi_zbaseline.npy", Fz_rescaled)
        np.save(export_path / "roi_z_scaling.npy", b)

        try:
            import matplotlib.pyplot as plt

            plt.figure()
            plt.plot(zpos)
            plt.xlabel("Frame")
            plt.ylabel("Z position (µm)")
            plt.tight_layout()
            plt.savefig(export_path / "roi_z_drift.png")
            plt.close()

            plt.figure()
            plt.hist(b, bins=30)
            plt.xlabel("Scaling factor")
            plt.ylabel("Count")
            plt.tight_layout()
            plt.savefig(export_path / "roi_z_scaling_hist.png")
            plt.close()
        except Exception as e:
            log_and_print(f"Could not save diagnostic plots: {e}", level="warning")

    log_and_print("ROI z-motion correction completed.")
    return export_path
