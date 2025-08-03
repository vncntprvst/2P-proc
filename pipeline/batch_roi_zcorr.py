# -*- coding: utf-8 -*-
"""Batch execution of ROI z-motion correction."""

import argparse
import json
import logging
import datetime
import os
from pathlib import Path

from pipeline import pipeline_roi_zcorr as roi_z


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file", nargs="+", help="Input configuration JSON file")
    args = parser.parse_args()

    for cfg_path in args.config_file:
        with open(cfg_path) as f:
            config = json.load(f)

        paths_cfg = config.get("paths", {})
        export_paths = paths_cfg.get("export_paths", [])

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
        logging.info("Starting ROI z-motion correction for data in " + cfg_path)

        params = {"params_mcorr": config.get("params_mcorr", {})}

        for export_path in export_paths:
            export_path = Path(export_path)
            logging.info("Export path: " + str(export_path))
            roi_z.run_roi_zcorr(export_path, params)

        logging.shutdown()


if __name__ == "__main__":
    main()
