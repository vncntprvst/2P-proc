# -*- coding: utf-8 -*-
"""BATCH_MCORR

Batch execution of motion correction.
"""

import argparse
import json
import logging
import datetime
import os, sys
from pathlib import Path

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Suppress TensorFlow warnings
os.environ['CUDA_VISIBLE_DEVICES'] = '0'  # Use first GPU if available
os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'  # Prevent TF from taking all GPU memory
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0' # Disable the Intel OneAPI Deep Neural Network Library optimizations
os.environ['TF_CPP_VMODULE'] = 'cuda_dnn=0,cuda_fft=0,cuda_blas=0' # Prevent TensorFlow from logging CUDA-related warnings

# Patch TensorFlow's logging to suppress specific warnings
def filter_tensorflow_warnings():
    logging.getLogger('tensorflow').setLevel(logging.ERROR)

filter_tensorflow_warnings()

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import pipeline_mcorr as preproc

def run_mcorr(
    data_path,
    params,
    regex_pattern="*_Ch2_*.ome.tif",
    recompute=True,
    output_format=False,
):
    """
    Run motion correction on a single dataset.

    Args:
        data_path (str or Path): Path to the input data directory.
        params (dict): Parameters for motion correction.
        regex_pattern (str): Regular expression pattern to match data files.
        recompute (bool): Whether to recompute existing results.
        output_format (bool or str): If not False, use the specified format for saving the motion-corrected movie.
            Options are 'h5', 'memmap' (default), or 'bin'.
    """
    # Validate mcorr format
    if output_format not in [False, 'h5', 'memmap', 'bin']:
        raise ValueError(
            "Invalid save_mcorr_movie format. "
            "Use 'false', 'memmap' (default), 'h5', or 'bin'."
        )
    
    _, batch_path = preproc.run_mcorr(
        data_path,
        params,
        regex_pattern=regex_pattern,
        recompute=recompute,
        output_format=output_format,
        )
    
    return batch_path

def main():
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
        help="Save final movie as binary file, either 'bin' or 'h5'. Default is False (a binary memmap is used temporarily and removed after cleanup)",
    )
    args = parser.parse_args()

    for cfg_path in args.config_file:
        with open(cfg_path) as f:
            config = json.load(f)

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
            log_path = os.path.dirname(export_paths[0])
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
        logging.info("Starting batch motion correction for data in " + cfg_path)

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
        # Remove fields not consumed by the motion-correction pipeline
        base_params_mcorr.pop("method", None)
        base_params_mcorr.pop("save_mcorr_movie", None)
        base_params = {
            "experimenter": config.get("experimenter", {}),
            "subject": config.get("subject", {}),
            "imaging": config.get("imaging", {}),
            "params_mcorr": base_params_mcorr,
            "params_extra": config.get("params_extra", {})
        }

        for i, data_path in enumerate(grouped_paths_list):
            if not isinstance(data_path, list):
                data_path = [Path(data_path)]
            else:
                data_path = [Path(p) for p in data_path]

            print(f"\n🔹 Processing Group {i+1}:")
            print("  Data path(s):", data_path)

            if i >= len(export_paths):
                print(f"⚠️ Warning: Missing export path for Group {i+1}. Skipping.")
                continue

            export_path = Path(export_paths[i])
            print("  Export path:", export_path)

            missing_paths = [p for p in data_path if not p.exists()]
            if missing_paths:
                print(f"❌ Data paths not found: {missing_paths}. Skipping.")
                continue

            params = json.loads(json.dumps(base_params))

            zstack_path = None
            if zstack_paths is not None:
                zstack_path = zstack_paths[i] if len(zstack_paths) > 1 else zstack_paths[0]
                if not os.path.exists(zstack_path):
                    print(f"❌ Z-stack path not found: {zstack_path}. Check the path.")
                    continue
                if z_motion_correction:
                    params["params_mcorr"]["z_motion_correction"] = z_motion_correction
                    params["zstack_path"] = str(zstack_path)

            logging.info("Data path: " + str(data_path))
            logging.info("Export path: " + str(export_path))
            logging.info("Parameters: " + str(params))

            params["export_path"] = str(export_path)

            params_path = Path.joinpath(export_path, "run_mcorr_arguments.json")
            export_path.mkdir(parents=True, exist_ok=True)
            save_params = {
                "data_path": [str(p) for p in data_path],
                "parameters": params,
                "regex_pattern": args.regex_pattern,
                "recompute": args.recompute,
            }
            with open(params_path, "w") as f:
                json.dump(save_params, f, indent=4)
           
            # Get save_mcorr_movie format from the config file
            save_mcorr_movie = config.get("params_mcorr", {}).get("save_mcorr_movie", "memmap")
            print(f"  Save motion-corrected movie format from config: {save_mcorr_movie}")
            # Override with command line argument if specified
            if args.save_binary:
                print(f"Overriding save_mcorr_movie with command line argument: {args.save_binary}")
                save_mcorr_movie = args.save_binary
            
            # Ensure valid format
            if save_mcorr_movie not in ['h5', 'memmap', 'bin']:
                print(f"Invalid save_mcorr_movie format: {save_mcorr_movie}. Using 'memmap'")
                save_mcorr_movie = 'memmap'
                
            logging.info("Save motion-corrected movie as: " + str(save_mcorr_movie))
            
            batch_path = run_mcorr(
                data_path,
                params,
                regex_pattern=args.regex_pattern,
                recompute=args.recompute,
                output_format=save_mcorr_movie,
            )

            logging.info("Batch path: " + str(batch_path))

        logging.shutdown()

if __name__ == "__main__":
    main()
