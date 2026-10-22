# -*- coding: utf-8 -*-
"""Register cells across separately processed sessions (same field of view).

Usage
-----
    python -m pipeline.register_sessions --exports <export1> <export2> ... --out <dir> \
        [--method roicat|track2p|caiman] [--um-per-pixel 1.45] [--python /path/to/python]
    python -m pipeline.register_sessions --config config.json   # uses paths.export_paths and
                                                                # params_registration

params_registration (config): {"method": "roicat", "out_dir": "...", "python": null,
"iscell_file": "iscell.npy", "cpu": false}. um_per_pixel defaults to imaging.microns_per_pixel. The roicat
and track2p methods run in an interpreter that has the package: --python, $ROICAT_PYTHON /
$TRACK2P_PYTHON, or the current one.
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.cell_registration import run_registration  # noqa: E402
from pipeline.utils.config_loader import load_config  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--exports", nargs="+", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--method", default=None)
    ap.add_argument("--um-per-pixel", type=float, default=None)
    ap.add_argument("--python", default=None)
    ap.add_argument("--iscell-file", default=None)
    ap.add_argument("--cpu", action="store_true", help="roicat: run on CPU even if a GPU is visible")
    args = ap.parse_args(argv)

    cfg = load_config(args.config) if args.config else {}
    reg = cfg.get("params_registration", {})
    exports = args.exports or cfg.get("paths", {}).get("export_paths", [])
    if len(exports) < 2:
        ap.error("need at least two export directories (--exports or paths.export_paths)")
    method = args.method or reg.get("method", "roicat")
    um = args.um_per_pixel or reg.get("um_per_pixel") or cfg.get("imaging", {}).get("microns_per_pixel", 1.45)
    out = args.out or reg.get("out_dir") or os.path.join(os.path.commonpath(exports), f"cell_registration_{method}")
    assignments, qc = run_registration(
        exports, out, method=method, um_per_pixel=float(um), python=args.python or reg.get("python"),
        iscell_file=args.iscell_file or reg.get("iscell_file", "iscell.npy"), cpu=args.cpu or reg.get("cpu", False))
    print(json.dumps({k: qc[k] for k in ("n_rois", "n_cells_tracked_in_k_sessions", "pairs")}, indent=2))
    print(f"Saved {len(assignments)} tracked cells to {out}")


if __name__ == "__main__":
    main()
