"""Export the registration benchmark cases as CellReg inputs.

Each case is a folder with session_<k>.mat holding a sparse footprint matrix A (n_roi x
Ly*Lx, C-order pixel index) and dims, plus case.json (session sources and, for deformed
sessions, the original ROI ids). Sessions are rebuilt exactly as in bench_splithalf.py,
bench_sameday.py, bench_crossday.py and negative_control.py.

Usage: python validation/registration/cellreg/export_cellreg_inputs.py --out <dir>
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import savemat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_splithalf import CONDITIONS, UM  # noqa: E402
from negative_control import shift_footprints  # noqa: E402
from regbench import deform, load_suite2p_session, to_sparse  # noqa: E402

A = Path("/home/wanglab/data/2P/Analysis_2P/Scnn1aAi14_D1M2")
P = {
    "h1": A / "08292026/run1_half1/suite2p/plane0", "h2": A / "08292026/run1_half2/suite2p/plane0",
    "run1": A / "08292026/run1/suite2p/plane0", "run2": A / "08292026/run2/suite2p/plane0",
    "d0824": A / "08242026/run1/suite2p/plane0", "d0828": A / "08282026/run1/suite2p/plane0",
    "d0829": A / "08292026/run1/suite2p/plane0", "d0831": A / "08312026/run1/suite2p/plane0",
    "joint": A / "08292026/run1run2/suite2p/plane0",
}


def write_case(out, name, sessions, meta):
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    for k, s in enumerate(sessions, 1):
        savemat(d / f"session_{k}.mat", {"A": to_sparse(s, "C").T.tocsr().astype(np.float64),
                                         "dims": np.array(s["dims"], float)}, do_compression=True)
    (d / "case.json").write_text(json.dumps(meta, indent=1))
    print(name, [len(s["masks"]) for s in sessions])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    ses = {k: load_suite2p_session(v) for k, v in P.items() if k != "joint"}
    for amp, rot, shift in CONDITIONS:
        key = f"amp{amp}_rot{rot}_shift{shift[0]},{shift[1]}"
        b = deform(ses["h2"], amp, UM, rot_deg=rot, shift_um=shift, seed=int(amp * 10 + rot * 7))
        write_case(args.out, f"splithalf__{key}", [ses["h1"], b],
                   {"kind": "splithalf", "condition": key, "ids2": b["ids"].tolist()})
    write_case(args.out, "sameday__run1-run2", [ses["run1"], ses["run2"]], {"kind": "sameday"})
    for a, b in [("d0829", "d0831"), ("d0824", "d0829"), ("d0824", "d0831"), ("d0829", "d0828")]:
        write_case(args.out, f"crossday__{a}_{b}", [ses[a], ses[b]], {"kind": "crossday", "pair": [a, b]})
    write_case(args.out, "crossday__d0824_d0829_d0831", [ses["d0824"], ses["d0829"], ses["d0831"]],
               {"kind": "crossday_multi"})
    write_case(args.out, "negative__d0829_d0831shift60", [ses["d0829"], shift_footprints(ses["d0831"], int(round(60 / UM)))],
               {"kind": "negative"})


if __name__ == "__main__":
    main()
