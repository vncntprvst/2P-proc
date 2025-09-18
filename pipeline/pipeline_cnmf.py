"""CNMF extraction pipeline step and CLI runner."""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules import extraction
from pipeline.utils.pipeline_utils import (
    log_and_print,
    memory_manager,
    cleanup_files,
    find_latest_batch,
)
from pipeline.utils.config_loader import load_config


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file", nargs="+", help="Input configuration JSON file")
    parser.add_argument(
        "--mcorr-output",
        dest="mcorr_output",
        default=None,
        help="Path to a motion corrected movie to use if motion correction was skipped",
    )
    return parser.parse_args(argv)


def _deepcopy_dict(data: dict) -> dict:
    return json.loads(json.dumps(data))


def _process_config(cfg_path: str, args: argparse.Namespace) -> None:
    config = load_config(cfg_path)

    paths_cfg = config.get("paths", {})
    data_paths = paths_cfg.get("data_paths", [])
    export_paths = paths_cfg.get("export_paths", [])
    concatenation_groups = paths_cfg.get("concatenation_groups", None)

    logging_cfg = config.get("logging", {})
    if logging_cfg:
        log_path = logging_cfg.get("log_path", os.path.dirname(export_paths[0]))
        log_level = logging_cfg.get("log_level", "INFO")
    else:
        log_path = os.path.dirname(export_paths[0]) if export_paths else Path.cwd()
        log_level = "INFO"

    os.makedirs(log_path, exist_ok=True)
    log_file = os.path.join(
        log_path, datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    )
    print("\n")
    print("Log file: " + log_file)
    print("\n")
    logging.basicConfig(
        filename=log_file,
        level=log_level,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info("Starting batch CNMF extraction for data in %s", cfg_path)

    if concatenation_groups:
        grouped_paths = {}
        for index, path in zip(concatenation_groups, data_paths):
            grouped_paths.setdefault(index, []).append(path)
        grouped_paths_list = list(grouped_paths.values())
    else:
        grouped_paths_list = [[p] for p in data_paths]

    print("\n🔹 Runs will be processed as follows:")
    for group_num, paths in enumerate(grouped_paths_list, start=1):
        print(f"  * Group {group_num}:")
        for p in paths:
            print(f"    - {p}")
    print("\n")

    imaging_cfg = config.get("imaging", {})
    params_extraction_cfg = _deepcopy_dict(config.get("params_extraction", {}))
    extraction_main = params_extraction_cfg.setdefault("main", {})
    if "fr" not in extraction_main and "fr" in imaging_cfg:
        extraction_main["fr"] = imaging_cfg["fr"]

    base_params = {
        "params_extraction": params_extraction_cfg,
        "params_extra": config.get("params_extra", {}),
    }

    for i, data_group in enumerate(grouped_paths_list):
        data_group_paths = [Path(p) for p in data_group]
        print(f"\n🔹 Processing Group {i+1}:")
        print("  Data path(s):", data_group_paths)

        if i >= len(export_paths):
            print(f"⚠️ Warning: Missing export path for Group {i+1}. Skipping.")
            continue

        export_path = Path(export_paths[i])
        print("  Export path:", export_path)

        params = _deepcopy_dict(base_params)
        params["export_path"] = str(export_path)

        logging.info("Data path: %s", data_group_paths)
        logging.info("Export path: %s", export_path)
        logging.info("Parameters: %s", params)

        params_path = export_path / "run_cnmf_arguments.json"
        export_path.mkdir(parents=True, exist_ok=True)
        save_params = {
            "data_path": [str(p) for p in data_group_paths],
            "parameters": params,
        }
        with open(params_path, "w") as fh:
            json.dump(save_params, fh, indent=4)

        _, batch_path = run_cnmf(
            data_group_paths,
            params,
            mcorr_movie=args.mcorr_output,
        )

        logging.info("Batch path: %s", batch_path)

    logging.shutdown()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    for cfg_path in args.config_file:
        _process_config(cfg_path, args)


if __name__ == "__main__":
    main()
