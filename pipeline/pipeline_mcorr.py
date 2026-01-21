"""Motion correction pipeline step.

This module wraps the motion correction workflow.
It can be executed independently of ROI extraction. 

Usage:
    python -m pipeline.pipeline_mcorr path/to/config.json
    (equivalent to `python pipeline/pipeline_mcorr.py path/to/config.json`)

Input:
    A configuration JSON file specifying data paths, export paths, and parameters.
    See `pipeline/configs/` for examples.

Output:
    Motion-corrected movies, and associated batch files if using the caiman pipeline (memmap format).
    Files are saved in the specified export paths

"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Suppress TensorFlow warnings
os.environ['CUDA_VISIBLE_DEVICES'] = '0'  # Use first GPU if available
os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'  # Prevent TF from taking all GPU memory
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0' # Disable the Intel OneAPI Deep Neural Network Library optimizations
os.environ['TF_CPP_VMODULE'] = 'cuda_dnn=0,cuda_fft=0,cuda_blas=0' # Prevent TensorFlow from logging CUDA-related warnings

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules import motion_correction as mcorr
from pipeline.utils.pipeline_utils import (
    log_and_print,
    memory_manager,
    cleanup_files,
)
from pipeline.utils.config_loader import load_config


def _suppress_tensorflow_logging() -> None:
    logging.getLogger('tensorflow').setLevel(logging.ERROR)


_suppress_tensorflow_logging()

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
    output_format : {"memmap", "h5", "bin", False}
        Format of the saved movie.
        If not False, use the specified format for saving the motion-corrected movie.
        Options are 'h5', 'memmap' (default), 'tiff' or 'bin'. 
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

    preserve_batch = False
    if output_format == "memmap":
        log_and_print(
            "Output format is 'memmap'. Configuring cleanup to preserve the memory-mapped file.",
            level="warning"
        )
        preserve_batch = True
        
    if postproc_cleanup:
        cleanup_files(batch_path, export_path, preserve_batch=preserve_batch)
    else:
        log_and_print(
            f"Keeping batch files associated to {batch_path}.", level="warning"
        )

    return export_path, batch_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file", nargs="+", help="Input configuration JSON file")
    parser.add_argument(
        "-rp",
        "--regex_pattern",
        default="*_Ch2_*.ome.tif",
        help="Regular expression pattern to match the data files",
    )
    parser.add_argument(
        "-rc",
        "--recompute",
        action="store_false",
        default=True,
        help="Recompute the motion correction even if the batch folder exists",
    )
    parser.add_argument(
        "--save-binary",
        default=False,
        help=(
            "Save final movie as binary file, either 'bin', 'tiff', or 'h5'. "
            "Default is False (a binary memmap is used temporarily and removed after cleanup)"
        ),
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
    zstack_paths = paths_cfg.get("zstack_paths", None)

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
    logging.info("Starting batch motion correction for data in %s", cfg_path)

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

    base_params_mcorr = config.get("params_mcorr", {}).copy()
    z_motion_correction = base_params_mcorr.pop("z_motion_correction", None)
    base_params_mcorr.pop("method", None)
    base_params_mcorr.pop("save_mcorr_movie", None)
    base_params = {
        "experimenter": config.get("experimenter", {}),
        "subject": config.get("subject", {}),
        "imaging": config.get("imaging", {}),
        "params_mcorr": base_params_mcorr,
        "params_extraction": config.get("params_extraction", {}),
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

        missing_paths = [p for p in data_group_paths if not p.exists()]
        if missing_paths:
            print(f"❌ Data paths not found: {missing_paths}. Skipping.")
            continue

        params = _deepcopy_dict(base_params)

        zstack_path = None
        if zstack_paths is not None:
            zstack_path = zstack_paths[i] if len(zstack_paths) > 1 else zstack_paths[0]
            if not os.path.exists(zstack_path):
                print(f"❌ Z-stack path not found: {zstack_path}. Check the path.")
                continue
            if z_motion_correction:
                params["params_mcorr"]["z_motion_correction"] = z_motion_correction
                params["zstack_path"] = str(zstack_path)

        logging.info("Data path: %s", data_group_paths)
        logging.info("Export path: %s", export_path)
        logging.info("Parameters: %s", params)

        params["export_path"] = str(export_path)

        params_path = export_path / "run_mcorr_arguments.json"
        export_path.mkdir(parents=True, exist_ok=True)
        save_params = {
            "data_path": [str(p) for p in data_group_paths],
            "parameters": params,
            "regex_pattern": args.regex_pattern,
            "recompute": args.recompute,
        }
        with open(params_path, "w") as fh:
            json.dump(save_params, fh, indent=4)

        save_mcorr_movie = config.get("params_mcorr", {}).get("save_mcorr_movie", "memmap")
        print(f"  Save motion-corrected movie format from config: {save_mcorr_movie}")
        if args.save_binary:
            print(f"Overriding save_mcorr_movie with command line argument: {args.save_binary}")
            save_mcorr_movie = args.save_binary

        if save_mcorr_movie not in ['h5', 'memmap', 'bin', 'tiff']:
            print(f"Invalid save_mcorr_movie format: {save_mcorr_movie}. Using 'memmap'")
            save_mcorr_movie = 'memmap'

        logging.info("Save motion-corrected movie as: %s", save_mcorr_movie)

        _, batch_path = run_mcorr(
            data_group_paths,
            params,
            regex_pattern=args.regex_pattern,
            recompute=args.recompute,
            output_format=save_mcorr_movie,
        )

        logging.info("Batch path: %s", batch_path)

    logging.shutdown()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    for cfg_path in args.config_file:
        _process_config(cfg_path, args)


if __name__ == "__main__":
    main()
