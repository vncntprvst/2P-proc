"""Correction-method comparison sweep (synthetic ground truth).

Runs the per-pixel / per-patch / per-ROI F_anat correction across a range of
z-drift amplitudes (one point per plane) and records, for each method, the
recovery of the true activity and the residual z-contamination. Also captures
example ΔF/F traces at a representative amplitude for an illustrative excerpt.

Outputs (into --out):
  stage3_sweep.json    [{z_amp, none/per_roi/per_pixel/per_patch:{recovery_r,
                        residual_z_r}}, ...]
  stage3_traces.npz    example true / uncorrected / per-ROI-corrected ΔF/F traces

Run (pixi env — needs compute_zcorrel):
  pixi run python validation/stage3_sweep.py --real-zstack <ZSeries> --out DIR
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.benchmarks.bruker_io import load_bruker_zstack
from tests.benchmarks.benchmark_correction_methods import run_correction_benchmark

METHODS = ["none", "per_roi", "per_pixel", "per_patch"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--real-zstack", type=Path, required=True)
    p.add_argument("--downsample", type=int, default=2)
    p.add_argument("--n-frames", type=int, default=200)
    p.add_argument(
        "--amps",
        type=str,
        default="1,2,3,4,5,6,7,8",
        help="comma-separated z-drift amplitudes (planes), one point each",
    )
    p.add_argument(
        "--trace-amp", type=float, default=5.0, help="amplitude at which to capture example traces"
    )
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vol, _ = load_bruker_zstack(args.real_zstack, channel=2, downsample=args.downsample)
    amps = [float(a) for a in args.amps.split(",") if a.strip()]

    sweep = []
    for a in amps:
        res = run_correction_benchmark(
            vol, n_frames=args.n_frames, amplitude_planes=a, n_cells=50, z_band=6, seed=args.seed
        )
        row = {"z_amp": a}
        for m in METHODS:
            row[m] = {"recovery_r": res[m]["recovery_r"], "residual_z_r": res[m]["residual_z_r"]}
        sweep.append(row)
        print(
            f"amp {a}: "
            + "  ".join(
                f"{m} r={res[m]['recovery_r']:.2f}/z={res[m]['residual_z_r']:.2f}" for m in METHODS
            )
        )
    (args.out / "stage3_sweep.json").write_text(json.dumps(sweep, indent=2))

    # Example traces at the representative amplitude.
    res = run_correction_benchmark(
        vol,
        n_frames=args.n_frames,
        amplitude_planes=args.trace_amp,
        n_cells=50,
        z_band=6,
        seed=args.seed,
        return_traces=True,
    )
    tr = res["_traces"]
    np.savez(
        args.out / "stage3_traces.npz",
        true_dff=tr["true_dff"],
        none=tr["none"],
        per_roi=tr["per_roi"],
        z_true=tr["z_true"],
        z_cell=tr["z_cell"],
        trace_amp=np.float32(args.trace_amp),
    )
    print(f"wrote {args.out/'stage3_sweep.json'} and stage3_traces.npz")


if __name__ == "__main__":
    main()
