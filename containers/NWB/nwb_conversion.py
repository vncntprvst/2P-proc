"""Convert 2P imaging data and analysis results to NWB.

This script expects a configuration JSON file formatted like
``pipeline/configs/config_template.json``. It can optionally convert the raw
imaging data, the processed segmentation output, or both. The resulting NWB file
is validated with ``nwbinspector`` and saved to a ``nwb`` subdirectory within the
export path.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from datetime import datetime

from neuroconv import NWBConverter
from neuroconv.datainterfaces import (
    MultiFileTiffImagingInterface,
    Suite2pSegmentationInterface,
)
from nwbinspector import inspect_nwb, save_report


class TwoPhotonNWBConverter(NWBConverter):
    """NWBConverter for 2-photon imaging data with optional segmentation."""

    data_interface_classes = {
        "imaging": MultiFileTiffImagingInterface,
        "segmentation": Suite2pSegmentationInterface,
    }


def _build_metadata(cfg: dict) -> dict:
    """Construct minimal NWB metadata from the configuration file."""

    subject = cfg.get("subject", {})
    imaging = cfg.get("imaging", {})

    # Parse dates
    session_date = imaging.get("date", "")
    session_start_time = None
    if session_date:
        try:
            session_start_time = datetime.strptime(session_date, "%d%m%Y")
        except ValueError:
            pass

    dob = subject.get("DOB", "")
    date_of_birth = None
    if dob:
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                date_of_birth = datetime.strptime(dob, fmt).date()
                break
            except ValueError:
                continue

    metadata = {
        "NWBFile": {
            "session_description": "2P calcium imaging session",
            "session_start_time": session_start_time,
        },
        "Subject": {
            "subject_id": subject.get("name", ""),
            "sex": subject.get("sex", "U"),
            "genotype": subject.get("genotype", ""),
            "date_of_birth": date_of_birth,
        },
    }

    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert 2P data to NWB.")
    parser.add_argument("config", help="Path to configuration JSON file.")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Convert only raw imaging data.",
    )
    parser.add_argument(
        "--processed",
        action="store_true",
        help="Convert only processed segmentation data.",
    )
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    convert_raw = args.raw or (not args.raw and not args.processed)
    convert_processed = args.processed or (not args.raw and not args.processed)

    data_paths = cfg["paths"].get("data_paths", [])
    export_paths = cfg["paths"].get("export_paths", [])
    if not export_paths:
        raise ValueError("No export paths specified in configuration file.")
    export_path = export_paths[0]

    nwb_dir = Path(export_path) / "nwb"
    nwb_dir.mkdir(parents=True, exist_ok=True)
    nwbfile_path = nwb_dir / f"{cfg['subject']['name']}_{cfg['imaging']['date']}.nwb"

    source_data = {}
    if convert_raw:
        source_data["imaging"] = {"file_paths": data_paths}
    if convert_processed:
        source_data["segmentation"] = {"folder_path": export_path}

    converter = TwoPhotonNWBConverter(source_data=source_data)
    metadata = converter.get_metadata()
    metadata.update(_build_metadata(cfg))

    converter.run_conversion(
        nwbfile_path=str(nwbfile_path),
        metadata=metadata,
        overwrite=True,
    )

    report = inspect_nwb(str(nwbfile_path))
    save_report(report, nwb_dir / "nwb_validation.txt")


if __name__ == "__main__":
    main()
