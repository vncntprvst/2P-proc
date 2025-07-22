# -*- coding: utf-8 -*-
"""extraction

Module implementing the constrained nonnegative matrix factorization (CNMF)
step of the Analysis 2P pipeline.

This module was extracted from :mod:`Mesmerize.pipeline_mcorr_cnmf` so that the
CNMF logic can be reused independently of the full pipeline.
"""

from __future__ import annotations

import json
import multiprocessing
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np
import mesmerize_core as mc
from scipy import io

from .motion_correction import log_and_print

__all__ = [
    "run_cnmf", 
    "save_processing_parameters", 
    "prepare_cnmf_object",
    "copy_mean_intensity_template",
    "export_cnmf_results"
]


def countdown(n: int) -> None:
    """Simple countdown timer used when prompting the user."""
    while n > 0:
        mins, secs = divmod(n, 60)
        timer = f"{mins:02d}:{secs:02d}"
        print(timer, end="\r")
        time.sleep(1)
        n -= 1


def run_cnmf(
    batch: Path,
    index: int,
    export_path: Path,
    params_cnmf: dict,
    data_path,
    z_correlation=None,
    z_motion_scaling_factors=None,
):
    """Run CNMF on a motion corrected movie and export results.

    Parameters
    ----------
    batch : Path
        Path to the Mesmerize batch file produced by motion correction.
    index : int
        Index of the motion correction item within the batch.
    export_path : Path
        Directory where outputs should be written.
    params_cnmf : dict
        Parameters for the CNMF algorithm.
    data_path : str or Path or list
        Original data location (used only for metadata in the saved parameters).
    z_correlation : np.ndarray, optional
        Pre-computed z correlation data.
    z_motion_scaling_factors : np.ndarray, optional
        Scaling factors from z motion subtraction (unused but kept for backwards
        compatibility).
    """

    # Load batch dataframe
    df = mc.load_batch(batch)

    # Add CNMF item using the motion corrected result
    df.caiman.add_item(
        algo="cnmf",
        input_movie_path=df.iloc[index],
        params=params_cnmf,
        item_name=df.iloc[index]["item_name"],
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
    save_processing_parameters(df, export_path, data_path, params_cnmf)
    
    # Get CNMF object and prepare it for export
    cnmf_obj = prepare_cnmf_object(df)
    
    # Copy the mean intensity template if available
    copy_mean_intensity_template(df, batch, export_path)
    
    # Export results to MATLAB format
    export_cnmf_results(df, cnmf_obj, export_path, z_correlation)

    return cnmf_obj


def save_processing_parameters(df, export_path, data_path, params_cnmf):
    """Save the parameters used for motion correction and CNMF processing.
    
    Parameters
    ----------
    df : pandas.DataFrame
        Mesmerize batch dataframe containing processing information.
    export_path : Path
        Directory where parameter file should be saved.
    data_path : str, Path, or list
        Original data location.
    params_cnmf : dict
        CNMF parameters used for processing.
    """
    params_path = export_path / "caiman_params.json"

    if isinstance(data_path, list):
        data_path = data_path[0]

    caiman_params = {
        "data_path": str(data_path),
        "export_path": str(export_path),
        "movie_name": str(df.iloc[0]["input_movie_path"]),
    }
    caiman_mcorr_params = df.iloc[0]["params"]["main"]
    caiman_mcorr_params["timestamp_mcorr"] = df.iloc[0]["ran_time"]
    caiman_cnmf_params = params_cnmf["main"] | df.iloc[-1]["params"]["main"]
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

    # Export to MATLAB format
    io.savemat(
        export_path / "results_caiman.mat",
        mdict={
            "mean_map_motion_corrected": df.iloc[0].caiman.get_projection("mean"),
            "spatial_components": cnmf_obj.estimates.A,
            "temporal_components": cnmf_obj.estimates.C,
            "background_spatial_component": cnmf_obj.estimates.b,
            "background_temporal_component": cnmf_obj.estimates.f,
            "residuals": cnmf_obj.estimates.R,
            "df_wo_bckgrnd": cnmf_obj.estimates.F_dff,
            "deconv_spk": cnmf_obj.estimates.S,
            "SNR_comp": cnmf_obj.estimates.SNR_comp,
            "baseline": np.array(cnmf_obj.estimates.bl, dtype=np.float32),
            "noise": np.array(cnmf_obj.estimates.neurons_sn, dtype=np.float32),
            "zpos": zpos,
        },
    )
    
    log_and_print(f"Saved results to {export_path}/results_caiman.mat.")

