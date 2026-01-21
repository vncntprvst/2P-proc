# -*- coding: utf-8 -*-
"""extraction

Module implementing the constrained nonnegative matrix factorization (CNMF)
step of the Analysis 2P pipeline.

This module was extracted from :mod:`Mesmerize.pipeline_mcorr_cnmf` so that the
CNMF logic can be reused independently of the full pipeline.
"""

from __future__ import annotations

import sys
import re
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import multiprocessing
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import mesmerize_core as mc
from scipy import io

from caiman.mmapping import load_memmap, prepare_shape
from caiman import save_memmap as save_memmap

from pipeline.utils.pipeline_utils import (
    log_and_print, 
    clip_range, 
    cat_movies_to_mp4,
    load_caiman_memmap,
)

__all__ = [
    "run_cnmf",
    "save_processing_parameters",
    "prepare_cnmf_object",
    "copy_mean_intensity_template",
    "export_cnmf_results",
]


def _prepare_cnmf_movie(mcorr_movie_path: str | Path, export_path: str | Path) -> Path:
    mcorr_movie_path = Path(mcorr_movie_path)
    export_path = Path(export_path)

    # Ensure export directory exists for saving memmaps
    if not export_path.exists():
        export_path.mkdir(parents=True, exist_ok=True)
    
    if mcorr_movie_path.suffix.lower() in {".h5", ".hdf5", ".tif", ".tiff"}:

        # Save memmap directly to export_path/mcorr to avoid tmp directory issues
        mcorr_movie_path = Path(
            save_memmap(
                [str(mcorr_movie_path)], 
                base_name=str(export_path / "mcorr"), 
                order="C",
                dview=None
            )
        )

    try:
        RelPath = mcorr_movie_path.relative_to(export_path)
    except ValueError:
        # Path is not relative to export path (e.g. it's in /tmp)
        new_path = export_path / mcorr_movie_path.name
        if new_path.exists():
            if new_path.stat().st_size == mcorr_movie_path.stat().st_size:
                    mcorr_movie_path = new_path
            else:
                    shutil.move(mcorr_movie_path, new_path)
                    mcorr_movie_path = new_path
        else:
            shutil.move(mcorr_movie_path, new_path)
            mcorr_movie_path = new_path
        log_and_print(f"Moved temporary memmap to {mcorr_movie_path}")

    return mcorr_movie_path


def _mean_projection_from_memmap(
    movie_path: Path,
    chunk_size: int = 200,
    max_frames: int | None = None,
) -> np.ndarray:
    adapter = load_caiman_memmap(movie_path)
    T, Ly, Lx = adapter.shape
    if max_frames is not None:
        T = min(T, max_frames)
    running_sum = np.zeros((Ly, Lx), dtype=np.float64)
    for start in range(0, T, chunk_size):
        stop = min(T, start + chunk_size)
        running_sum += adapter[start:stop].sum(axis=0, dtype=np.float64)
    adapter.close()
    return (running_sum / float(T)).astype(np.float32)


def _mean_projection_from_tiff(
    movie_path: Path,
    max_frames: int | None = None,
) -> np.ndarray:
    import tifffile

    running_sum = None
    count = 0
    with tifffile.TiffFile(movie_path) as tif:
        for page in tif.pages:
            frame = page.asarray()
            if running_sum is None:
                running_sum = np.zeros_like(frame, dtype=np.float64)
            running_sum += frame.astype(np.float64, copy=False)
            count += 1
            if max_frames is not None and count >= max_frames:
                break
    if running_sum is None or count == 0:
        raise ValueError(f"No frames found in {movie_path}")
    return (running_sum / float(count)).astype(np.float32)


def _mean_projection_from_h5(
    movie_path: Path,
    max_frames: int | None = None,
) -> np.ndarray:
    import h5py

    with h5py.File(movie_path, "r") as f:
        if "data" in f:
            dset = f["data"]
        else:
            keys = [k for k in f.keys()]
            if not keys:
                raise ValueError(f"No datasets found in {movie_path}")
            dset = f[keys[0]]
        T = dset.shape[0]
        if max_frames is not None:
            T = min(T, max_frames)
        running_sum = np.zeros(dset.shape[1:], dtype=np.float64)
        for start in range(0, T, 200):
            stop = min(T, start + 200)
            running_sum += dset[start:stop].sum(axis=0, dtype=np.float64)
    return (running_sum / float(T)).astype(np.float32)


def _mean_projection_from_path(
    movie_path: str | Path,
    max_frames: int | None = None,
) -> np.ndarray:
    movie_path = Path(movie_path)
    suffix = movie_path.suffix.lower()
    if suffix in {".mmap", ".npy"}:
        return _mean_projection_from_memmap(movie_path, max_frames=max_frames)
    if suffix in {".tif", ".tiff", ".btf"}:
        return _mean_projection_from_tiff(movie_path, max_frames=max_frames)
    if suffix in {".h5", ".hdf5", ".n5", ".zarr"}:
        return _mean_projection_from_h5(movie_path, max_frames=max_frames)

    import caiman as cm
    movie = cm.load(str(movie_path))
    return np.mean(movie, axis=0).astype(np.float32)


def _coerce_matlab_value(value):
    if value is None:
        return np.array([])
    return value


def countdown(n: int) -> None:
    """Simple countdown timer used when prompting the user."""
    while n > 0:
        mins, secs = divmod(n, 60)
        timer = f"{mins:02d}:{secs:02d}"
        print(timer, end="\r")
        time.sleep(1)
        n -= 1

def create_components_movie(batch_path, export_path, mcorr_movie_path=None, cnmf_obj=None, index=-1, excerpt=None):
    """
    Create a movie concatenating the components and the residuals.
    """
    # if mcorr_movie is not a string, load the data frame from the batch
    # if not isinstance(mcorr_movie, str):
    if batch_path is not None:
        df = mc.load_batch(batch_path)
        # Load the motion corrected movie
        # mcorr_movie = df.iloc[index].caiman.get_input_movie()
        # Load the components (reconstructed movie with no background)
        neural_activity_movie = df.iloc[index].cnmf.get_rcm() 
        # image_neural_activity = neural_activity_movie[0,:,:]
        # Load the residuals
        residuals_movie = df.iloc[index].cnmf.get_residuals()
        # image_residuals = residuals_movie[0,:,:]
    else:
        mcorr_movie_path = _prepare_cnmf_movie(mcorr_movie_path, export_path)
        mcorr_movie, dims, T = load_memmap(str(mcorr_movie_path))
        mcorr_movie = np.reshape(mcorr_movie.T, [T] + list(dims), order='F')
        mcorr_movie = mcorr_movie.transpose(0, 2, 1)
             
        # # If cnmf_obj is not a CNMF object, load the data frame from the batch path
        # if isinstance(cnmf_obj, str):
        #     # Load the data frame from the batch
        #     df = mc.load_batch(batch_path)
        #     # Load the CNMF results
        #     cnmf_obj = df.iloc[index].cnmf.get_output()
        #     # Keep only accepted components
        #     cnmf_obj.estimates.select_components(use_object=True)
        #     # Compute dF/F
        #     if cnmf_obj.estimates.F_dff is None:
        #         print('Calculating estimates.F_dff')
        #         cnmf_obj.estimates.detrend_df_f(quantileMin=8, 
        #                                         frames_window=400,
        #                                         use_residuals=False)
    
        # reconstruct denoised components movie
        neural_activity = cnmf_obj.estimates.A @ cnmf_obj.estimates.C  # A ⊗ C
        # reshape neural activity to movie dimensions
        dims = cnmf_obj.dims
        T = cnmf_obj.estimates.C.shape[1]
        neural_activity_movie = np.reshape(neural_activity.T, [T] + list(dims), order='F')
        
        # If residuals_movie is not defined, reconstruct it
        # if 'residuals_movie' not in locals():

        # reconstruct background movie
        background = cnmf_obj.estimates.b @ cnmf_obj.estimates.f  # b ⊗ f
        # reconstruct denoised movie
        denoised_movie = neural_activity + background  # AC + bf
        # reshape denoised movie to movie dimensions
        denoised_movie = np.reshape(denoised_movie.T, [T] + list(dims), order='F')
        # reconstruct residuals movie
        residuals_movie = mcorr_movie - denoised_movie # mcorr_movie - AC - bf
        # turn into a movie object
        # denoised_movie = cm.movie(denoised_movie).reshape(dims + (-1,), order='F').transpose([2, 0, 1])

    # If excerpt requested, keep only the first x frames of the movie
    if excerpt is not None:
        neural_activity_movie = neural_activity_movie[:excerpt]
        residuals_movie = residuals_movie[:excerpt]

    # Data is originally uint16, but values may extend beyond range, and converted to float at this point.
    # Clip the values to the uint16 range, and convert to uint16 data type
    neural_activity_movie = clip_range(neural_activity_movie, 'uint16').astype('uint16')
    residuals_movie = clip_range(residuals_movie, 'uint16').astype('uint16')

    # # Convert to uint8 to reduce file size further
    # neural_activity_movie = (neural_activity_movie / (2**16-1) * 255).astype('uint8')
    # residuals_movie = (residuals_movie / (2**16-1) * 255).astype('uint8')

    # Set the path of the mp4 movie
    movie_path = Path.joinpath(export_path, f"compare_components_residuals.mp4")

    # Concatenate the two movies horizontally
    cat_movies_to_mp4(neural_activity_movie, residuals_movie, movie_path)
    
    log_and_print(f"Saved components movie to {export_path}/components_movie.mp4")

def run_cnmf(
    batch: Path,
    index: int | None,
    export_path: Path,
    params_extraction: dict,
    data_path,
    input_movie_path: str | Path | None = None,
    z_correlation=None,
    z_motion_scaling_factors=None,
):
    """Run CNMF on a motion corrected movie and export results.

    Parameters
    ----------
    batch : Path
        Path to the Mesmerize batch file produced by motion correction.
    index : int | None
        Index of the motion correction item within the batch. None if using input_movie_path.
    export_path : Path
        Directory where outputs should be written.
    params_extraction : dict
        Parameters for the CNMF algorithm.
    data_path : str or Path or list
        Original data location (used only for metadata in the saved parameters).
    input_movie_path : str | Path, optional
        Direct path to input movie if not using a batch item.
    z_correlation : np.ndarray, optional
        Pre-computed z correlation data.
    z_motion_scaling_factors : np.ndarray, optional
        Scaling factors from z motion subtraction (unused but kept for backwards
        compatibility).
    """
    # Set the parent raw data path before any batch operations
    mc.set_parent_raw_data_path(Path(export_path))

    # Load batch dataframe
    df = mc.load_batch(batch)

    if input_movie_path is not None:
        mcorr_movie_path = Path(input_movie_path)
        item_name = mcorr_movie_path.stem
    elif index is not None:
        mcorr_movie_path=df.iloc[index]
        item_name = df.iloc[index]["item_name"]
    else:
        raise ValueError("Either index or input_movie_path must be provided.")

    if str(mcorr_movie_path).endswith((".h5", ".hdf5", ".tif", ".tiff")):
        mcorr_movie_path = _prepare_cnmf_movie(mcorr_movie_path, export_path)


    # Add CNMF item using the motion corrected result
    df.caiman.add_item(
        algo="cnmf",
        input_movie_path=mcorr_movie_path,
        params=params_extraction,
        item_name=item_name,
    )

    # Handle existing multiprocessing children from previous runs
    if len(multiprocessing.active_children()) > 0:
        import select

        print("There are active processes : ")
        for p in multiprocessing.active_children():
            print(p)
        print("Do you want to kill them ? (y/n)")

        t = threading.Thread(target=countdown, args=(300,))
        t.start()

        i, _, _ = select.select([sys.stdin], [], [], 300)
        if i:
            answer = sys.stdin.readline().strip()
        else:
            print("Timeout, killing the processes.")
            answer = "y"

        if answer == "y":
            print("Killing processes")
            for p in multiprocessing.active_children():
                p.terminate()
                p.join()
        else:
            print("CNMF may not run properly if a cluster is already running.")

    # Run CNMF for items that haven't been processed yet
    for _, row in df.iterrows():
        if row.algo != "cnmf":
            continue
        if row["outputs"] is not None:
            continue

        log_and_print(
            f"Running batch item {row.name}, id {row.uuid}, algo {row.algo}."
        )
        process = row.caiman.run()

        if process.__class__.__name__ == "DummyProcess":
            df = df.caiman.reload_from_disk()

    log_and_print(f"Batch completed for CNMF. Results saved to {batch}.")

    # Reload to ensure we have the latest results
    df = df.caiman.reload_from_disk()

    # Save parameters and export results
    save_processing_parameters(df, export_path, data_path, params_extraction)
    
    # Get CNMF object and prepare it for export
    cnmf_obj = prepare_cnmf_object(df)
    
    # Copy the mean intensity template if available
    copy_mean_intensity_template(df, batch, export_path)
    
    # Export results to MATLAB format
    export_cnmf_results(df, cnmf_obj, export_path, z_correlation)

    return cnmf_obj


def save_processing_parameters(df, export_path, data_path, params_extraction):
    """Save the parameters used for motion correction and CNMF processing.
    
    Parameters
    ----------
    df : pandas.DataFrame
        Mesmerize batch dataframe containing processing information.
    export_path : Path
        Directory where parameter file should be saved.
    data_path : str, Path, or list
        Original data location.
    params_extraction : dict
        CNMF parameters used for processing.
    """
    params_path = export_path / "caiman_params.json"

    if isinstance(data_path, list):
        data_path = data_path[0]

    # Use the first batch item to identify the original input movie if possible
    # This preserves the logic to point to the raw data (input of mcorr) rather than the mcorr output
    movie_name = str(df.iloc[0]["input_movie_path"])

    caiman_params = {
        "data_path": str(data_path),
        "export_path": str(export_path),
        "movie_name": movie_name,
    }
    
    # Attempt to retrieve motion correction parameters from the batch history
    caiman_mcorr_params = {}
    
    # Check if we have mcorr items in the batch
    # We filter by algo to be safe
    mcorr_items = df[df["algo"] == "mcorr"]
    if not mcorr_items.empty:
        # Use the first mcorr item found
        caiman_mcorr_params = mcorr_items.iloc[0]["params"]["main"]
        caiman_mcorr_params["timestamp_mcorr"] = mcorr_items.iloc[0]["ran_time"]
    
    # Get CNMF parameters
    # Merge passed params with what's in the dataframe to be sure
    caiman_cnmf_params = params_extraction["main"] 
    if "params" in df.columns and "main" in df.iloc[-1]["params"]:
         caiman_cnmf_params = caiman_cnmf_params | df.iloc[-1]["params"]["main"]
    
    caiman_cnmf_params["timestamp_cnmf"] = df.iloc[-1]["ran_time"]
    
    caiman_params = caiman_params | caiman_mcorr_params | caiman_cnmf_params

    with open(params_path, "w") as f:
        json.dump(caiman_params, f, indent=4)

    log_and_print(f"Saved parameters to {params_path}.")


def prepare_cnmf_object(df):
    """Prepare the CNMF object for export by selecting components and calculating dF/F.
    
    Parameters
    ----------
    df : pandas.DataFrame
        Mesmerize batch dataframe containing processing information.
        
    Returns
    -------
    cnmf_obj : caiman.source_extraction.cnmf.cnmf.CNMF
        Prepared CNMF object with selected components and calculated F_dff.
    """
    cnmf_obj = df.iloc[-1].cnmf.get_output()
    
    # Select components
    cnmf_obj.estimates.select_components(use_object=True)
    
    # Calculate dF/F if not already calculated
    if cnmf_obj.estimates.F_dff is None:
        log_and_print("Calculating estimates.F_dff")
        cnmf_obj.estimates.detrend_df_f(
            quantileMin=8, frames_window=400, use_residuals=False
        )
    
    return cnmf_obj


def copy_mean_intensity_template(df, batch, export_path):
    """Copy the mean intensity template file to the export directory.
    
    Parameters
    ----------
    df : pandas.DataFrame
        Mesmerize batch dataframe containing processing information.
    batch : Path
        Path to the Mesmerize batch file.
    export_path : Path
        Directory where template file should be copied.
    """
    cnmf_uuid = df[df["algo"] == "cnmf"]["uuid"].values[0]
    mean_intensity_template_path = batch.parent / cnmf_uuid / f"{cnmf_uuid}_cn.npy"
    
    if mean_intensity_template_path.exists():
        shutil.copy(mean_intensity_template_path, export_path / "mean_intensity_template.npy")
        log_and_print(f"Saved mean_intensity_template.npy to {export_path}.")
    else:
        log_and_print(
            f"Could not find cn.npy file at {mean_intensity_template_path}.")


def export_cnmf_results(df, cnmf_obj, export_path, z_correlation=None):
    """Export CNMF results to MATLAB format.
    
    Parameters
    ----------
    df : pandas.DataFrame
        Mesmerize batch dataframe containing processing information.
    cnmf_obj : caiman.source_extraction.cnmf.cnmf.CNMF
        CNMF object containing processing results.
    export_path : Path
        Directory where results should be saved.
    z_correlation : np.ndarray, optional
        Z correlation data if available.
    """
    # Get Z position information if available
    if z_correlation is None:
        zcorr_file = export_path / "z_correlation.npz"
        if zcorr_file.exists():
            z_correlation = np.load(zcorr_file)
            zpos = z_correlation["zpos"]
        else:
            zpos = np.array([np.nan])
    else:
        # Assume z_correlation is a dict-like object with "zpos" key
        zpos = z_correlation.get("zpos", np.array([np.nan]))

    mcorr_rows = df[df["algo"] == "mcorr"]
    if not mcorr_rows.empty:
        mean_map = mcorr_rows.iloc[0].caiman.get_projection("mean")
    else:
        # Use the input movie of the CNMF item
        movie_path = df.iloc[-1].caiman.get_input_movie()
        mean_map = _mean_projection_from_path(movie_path)

    # Export to MATLAB format
    io.savemat(
        export_path / "results_caiman.mat",
        mdict={
            "mean_map_motion_corrected": _coerce_matlab_value(mean_map),
            "spatial_components": _coerce_matlab_value(cnmf_obj.estimates.A),
            "temporal_components": _coerce_matlab_value(cnmf_obj.estimates.C),
            "background_spatial_component": _coerce_matlab_value(cnmf_obj.estimates.b),
            "background_temporal_component": _coerce_matlab_value(cnmf_obj.estimates.f),
            "residuals": _coerce_matlab_value(cnmf_obj.estimates.R),
            "df_wo_bckgrnd": _coerce_matlab_value(cnmf_obj.estimates.F_dff),
            "deconv_spk": _coerce_matlab_value(cnmf_obj.estimates.S),
            "SNR_comp": _coerce_matlab_value(cnmf_obj.estimates.SNR_comp),
            "baseline": _coerce_matlab_value(np.array(cnmf_obj.estimates.bl, dtype=np.float32) if cnmf_obj.estimates.bl is not None else None),
            "noise": _coerce_matlab_value(np.array(cnmf_obj.estimates.neurons_sn, dtype=np.float32) if cnmf_obj.estimates.neurons_sn is not None else None),
            "zpos": zpos,
        },
    )
    
    log_and_print(f"Saved results to {export_path}/results_caiman.mat.")
    
