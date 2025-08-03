"""Motion correction pipeline step.

This module wraps the motion correction workflow so it can be executed independently of extraction."""

from __future__ import annotations

from pathlib import Path

from modules import motion_correction as mcorr
from pipeline.utils.pipeline_utils import (
    log_and_print,
    memory_manager,
    cleanup_files,
)

def run_mcorr(
    data_path,
    parameters,
    regex_pattern="*_Ch2_*.ome.tif",
    recompute=True,
    output_format="memmap",
):
    """Run motion correction only.

    Parameters
    ----------
    data_path : list[Path] | Path
        Input data paths.
    parameters : dict
        Dictionary containing at least ``params_mcorr`` and ``export_path``.
    regex_pattern : str
        Pattern to match input files.
    recompute : bool
        Recompute motion correction even if outputs exist.
    output_format : {"memmap", "h5"}
        Format of the saved movie.
    """
    log_and_print("Starting motion correction pipeline.")
    export_path = Path(parameters["export_path"])
    export_path.mkdir(parents=True, exist_ok=True)

    with memory_manager("motion_correction"):
        mcorr_results = mcorr.run_motion_correction_workflow(
            data_path=data_path,
            export_path=export_path,
            parameters=parameters,
            regex_pattern=regex_pattern,
            recompute=recompute,
            create_movies=True,
            output_format=output_format,
        )

    batch_path = mcorr_results["batch_path"]

    postproc_cleanup = parameters.get("params_extra", {}).get("cleanup", False)
    if postproc_cleanup:
        cleanup_files(batch_path, export_path)
    else:
        log_and_print(
            f"Keeping batch files associated to {batch_path}.", level="warning"
        )

    return export_path, batch_path
