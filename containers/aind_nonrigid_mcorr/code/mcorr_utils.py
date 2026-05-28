"""
Thin wrapper around CaImAn/NoRMCorre motion correction.

Operates directly on numpy arrays without requiring a full config JSON or
mesmerize-core batch infrastructure. Temp files are cleaned up on exit.
"""

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np


def run_caiman_mcorr(
    movie,
    pw_rigid=True,
    max_shifts=(6, 6),
    strides=(48, 48),
    overlaps=(24, 24),
    niter_rig=1,
):
    """Run CaImAn non-rigid (or rigid) motion correction on a numpy array.

    The movie is first saved to a temporary memmap file that CaImAn can
    process, then the corrected frames are read back into a numpy array.
    All temporary files are removed in a finally block.

    Parameters
    ----------
    movie : np.ndarray
        Input movie, shape (T, H, W), float32.
    pw_rigid : bool
        If True, run piecewise-rigid (non-rigid) correction after rigid.
        If False, run rigid-only correction.
    max_shifts : tuple of int
        Maximum allowed shift (rows, cols) in pixels.
    strides : tuple of int
        Strides for patch grid in pw-rigid mode (rows, cols).
    overlaps : tuple of int
        Overlap between adjacent patches (rows, cols).
    niter_rig : int
        Number of iterations for the rigid pass.

    Returns
    -------
    tuple[np.ndarray, dict]
        corrected_movie : np.ndarray, shape (T, H, W), float32
        shifts_dict : dict with keys 'frame', 'x_shift', 'y_shift'.
            For pw-rigid, x_shift/y_shift are the mean shifts across patches
            per frame (representative of the global drift).
    """
    # Defer heavy imports so the module can be imported cheaply
    import caiman as cm
    from caiman.motion_correction import MotionCorrect
    from caiman.source_extraction.cnmf.params import CNMFParams

    # Ensure CAIMAN_TEMP is set so CaImAn knows where to write scratch files
    if "CAIMAN_TEMP" not in os.environ:
        os.environ["CAIMAN_TEMP"] = str(Path(tempfile.gettempdir()) / "caiman_temp")

    tmp_dir = Path(tempfile.mkdtemp(prefix="aind_mcorr_"))
    print(f"[mcorr_utils] Using temp directory: {tmp_dir}")

    try:
        # --- 1. Save input movie to a CaImAn-compatible memmap ---
        T, H, W = movie.shape
        tmp_tif = str(tmp_dir / "input_movie.tif")
        print(f"[mcorr_utils] Saving input movie ({T} frames, {H}x{W}) to temp TIFF...")
        import tifffile
        tifffile.imwrite(tmp_tif, movie.astype(np.float32))

        # --- 2. Build CaImAn params ---
        opts_dict = {
            "fnames": [tmp_tif],
            "pw_rigid": pw_rigid,
            "max_shifts": max_shifts,
            "strides": strides,
            "overlaps": overlaps,
            "niter_rig": niter_rig,
            # Disable cluster to run single-threaded inside the capsule
            "dview": None,
        }
        opts = CNMFParams(params_dict=opts_dict)

        # --- 3. Run motion correction ---
        print(f"[mcorr_utils] Starting CaImAn MotionCorrect (pw_rigid={pw_rigid})...")
        mc_obj = MotionCorrect([tmp_tif], dview=None, **opts.get_group("motion"))
        mc_obj.motion_correct(save_movie=True)
        print("[mcorr_utils] Motion correction complete.")

        # --- 4. Load corrected movie from memmap ---
        if pw_rigid and mc_obj.fname_tot_els is not None:
            corrected_fname = mc_obj.fname_tot_els[0]
        else:
            corrected_fname = mc_obj.fname_tot_rig[0]

        print(f"[mcorr_utils] Loading corrected movie from: {corrected_fname}")
        corrected_array, _, _ = cm.load_memmap(corrected_fname)
        # CaImAn memmap is (d1*d2, T); reshape to (T, H, W)
        corrected_movie = corrected_array.T.reshape(T, H, W).astype(np.float32)

        # --- 5. Extract shift estimates ---
        shifts_dict = _extract_shifts(mc_obj, pw_rigid, T)

        return corrected_movie, shifts_dict

    finally:
        # Clean up all temp files regardless of success or failure
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            print(f"[mcorr_utils] Cleaned up temp directory: {tmp_dir}")
        except Exception as cleanup_err:
            print(f"[mcorr_utils] WARNING: cleanup failed: {cleanup_err}")


def _extract_shifts(mc_obj, pw_rigid, n_frames):
    """Extract per-frame shift estimates from a completed MotionCorrect object.

    For piecewise-rigid correction, shifts are averaged across all patches to
    produce a single (x_shift, y_shift) representative of global frame drift.

    Parameters
    ----------
    mc_obj : caiman.motion_correction.MotionCorrect
        Completed motion correction object.
    pw_rigid : bool
        Whether piecewise-rigid correction was run.
    n_frames : int
        Total number of frames in the movie.

    Returns
    -------
    dict
        Keys: 'frame', 'x_shift', 'y_shift'.
    """
    frames = list(range(n_frames))

    if pw_rigid and hasattr(mc_obj, "x_shifts_els") and mc_obj.x_shifts_els is not None:
        # x_shifts_els and y_shifts_els are lists of length n_frames,
        # each element is an array of shifts across patches
        x_shifts_els = mc_obj.x_shifts_els
        y_shifts_els = mc_obj.y_shifts_els

        # Guard: if per-frame shift lists differ in length from n_frames, fall back
        if len(x_shifts_els) == n_frames:
            x_mean = [float(np.mean(s)) for s in x_shifts_els]
            y_mean = [float(np.mean(s)) for s in y_shifts_els]
        else:
            print(
                f"[mcorr_utils] WARNING: pw_rigid shift list length {len(x_shifts_els)} "
                f"!= n_frames {n_frames}; padding with zeros."
            )
            pad_len = n_frames - len(x_shifts_els)
            x_mean = [float(np.mean(s)) for s in x_shifts_els] + [0.0] * pad_len
            y_mean = [float(np.mean(s)) for s in y_shifts_els] + [0.0] * pad_len

        return {"frame": frames, "x_shift": x_mean, "y_shift": y_mean}

    # Rigid correction: shifts_rig is an (n_frames, 2) array [row_shift, col_shift]
    if hasattr(mc_obj, "shifts_rig") and mc_obj.shifts_rig is not None:
        shifts_rig = np.array(mc_obj.shifts_rig)  # shape (T, 2)
        if shifts_rig.ndim == 2 and shifts_rig.shape[1] >= 2:
            x_shifts = shifts_rig[:, 1].tolist()  # col = x
            y_shifts = shifts_rig[:, 0].tolist()  # row = y
        else:
            x_shifts = [0.0] * n_frames
            y_shifts = [0.0] * n_frames
    else:
        print("[mcorr_utils] WARNING: no shift data found; filling with zeros.")
        x_shifts = [0.0] * n_frames
        y_shifts = [0.0] * n_frames

    return {"frame": frames, "x_shift": x_shifts, "y_shift": y_shifts}
