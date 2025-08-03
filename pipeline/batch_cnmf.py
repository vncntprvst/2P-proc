# -*- coding: utf-8 -*-
"""BATCH_CNMF

Batch execution of CNMF extraction.
"""

import argparse
import json
import logging
import datetime
import os
from pathlib import Path

from pipeline import pipeline_cnmf as preproc


def run_cnmf(data_path, params, mcorr_output=None):
    """Run CNMF on a single dataset."""
    _, batch_path = preproc.run_cnmf(
        data_path,
        params,
        export_path=params["export_path"],
        mcorr_movie=mcorr_output,
    )
    return batch_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file", nargs="+", help="Input configuration JSON file")
    parser.add_argument(
        "--mcorr-output",
        dest="mcorr_output",
        default=None,
        help="Path to a motion corrected movie to use if motion correction was skipped",
    )
    args = parser.parse_args()

    for cfg_path in args.config_file:
        with open(cfg_path) as f:
            config = json.load(f)

        paths_cfg = config.get("paths", {})
        data_paths = paths_cfg.get("data_paths", [])
        export_paths = paths_cfg.get("export_paths", [])
        concatenation_groups = paths_cfg.get("concatenation_groups", None)

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
        logging.info("Starting batch CNMF extraction for data in " + cfg_path)

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

        base_params = {
            "params_extraction": config.get("params_extraction", {}),
            "params_extra": config.get("params_extra", {}),
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

            params = json.loads(json.dumps(base_params))
            params["export_path"] = str(export_path)

            logging.info("Data path: " + str(data_path))
            logging.info("Export path: " + str(export_path))
            logging.info("Parameters: " + str(params))

            params_path = Path.joinpath(export_path, "run_cnmf_arguments.json")
            export_path.mkdir(parents=True, exist_ok=True)
            save_params = {
                "data_path": [str(p) for p in data_path],
                "parameters": params,
            }
            with open(params_path, "w") as f:
                json.dump(save_params, f, indent=4)

            batch_path = run_cnmf(data_path, params, mcorr_output=args.mcorr_output)

            logging.info("Batch path: " + str(batch_path))

        logging.shutdown()

if __name__ == "__main__":
    main()
