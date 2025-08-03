"""CNMF extraction pipeline step.

Runs constrained non-negative matrix factorization on motion corrected data."""

from __future__ import annotations

from pathlib import Path

from modules import extraction
from pipeline.utils.pipeline_utils import (
    log_and_print,
    memory_manager,
    cleanup_files,
    find_latest_batch,
)


def run_cnmf(
    data_path,
    parameters,
    export_path=None,
    mcorr_movie=None,
):
    """Run CNMF extraction only.

    Parameters
    ----------
    data_path : list | Path
        Original data location for metadata logging.
    parameters : dict
        Dictionary containing at least ``params_extraction`` and ``export_path``.
    export_path : str or Path, optional
        Where to store the CNMF outputs.
    mcorr_movie : str or Path, optional
        Path to a motion-corrected movie to use when motion correction was
        performed externally and no batch files are present.
    """

    log_and_print("Starting CNMF extraction.")
    if export_path is None:
        export_path = Path(parameters["export_path"])
    else:
        export_path = Path(export_path)
    export_path.mkdir(parents=True, exist_ok=True)

    batch_path = None
    if mcorr_movie is None:
        try:
            batch_path = find_latest_batch(export_path)
        except FileNotFoundError:
            batch_path = None

    with memory_manager("cnmf"):
        params_cnmf = parameters["params_extraction"]
        if batch_path is not None and mcorr_movie is None:
            extraction.run_cnmf(batch_path, 0, export_path, params_cnmf, data_path)
            extraction.create_components_movie(
                batch_path=batch_path, export_path=export_path, excerpt=240
            )
        else:
            cnm_obj = extraction.run_cnmf_on_movie(
                mcorr_movie, export_path, params_cnmf
            )
            extraction.create_components_movie(
                batch_path=None,
                export_path=export_path,
                mcorr_movie_path=mcorr_movie,
                cnmf_obj=cnm_obj,
                excerpt=240,
            )

    postproc_cleanup = parameters.get("params_extra", {}).get("cleanup", True)
    if postproc_cleanup and batch_path is not None:
        cleanup_files(batch_path, export_path)
    elif batch_path is not None:
        log_and_print(
            f"Keeping batch files associated to {batch_path}.", level="warning"
        )

    return export_path, batch_path
