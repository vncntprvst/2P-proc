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
):
    """Run CNMF extraction only."""
    log_and_print("Starting CNMF extraction.")
    if export_path is None:
        export_path = Path(parameters["export_path"])
    else:
        export_path = Path(export_path)
    export_path.mkdir(parents=True, exist_ok=True)

    batch_path = find_latest_batch(export_path)
    index = 0

    with memory_manager("cnmf"):
        params_cnmf = parameters["params_extraction"]
        extraction.run_cnmf(batch_path, index, export_path, params_cnmf, data_path)
        extraction.create_components_movie(batch_path=batch_path, export_path=export_path, excerpt=240)

    postproc_cleanup = parameters.get("params_extra", {}).get("cleanup", True)
    if postproc_cleanup:
        cleanup_files(batch_path, export_path)
    else:
        log_and_print(
            f"Keeping batch files associated to {batch_path}.", level="warning"
        )

    return export_path, batch_path
