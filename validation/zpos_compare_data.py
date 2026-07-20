"""Generate z-position method-comparison data for the report.

Runs compute_zcorrel and compute_zcorrel_suite2p on identical inputs and saves:
  - synthetic mode: multi-seed accuracy stats vs ground truth  -> zpos_synthetic.json
  - real mode:      both methods' zpos on a real mcorr movie    -> <out>.npz
                    (with optional session boundaries for concatenated data)

Runs in the pixi env (needs suite2p). Real mode downsamples the mcorr TIFF in
chunks to stay within memory for long (concatenated) movies.

Usage
-----
  pixi run python zpos_compare_data.py synthetic --real-zstack <ZSeries> --seeds 8 --out DIR
  pixi run python zpos_compare_data.py real --mcorr-tiff <tiff> --zseries <ZSeries> \
      --downsample 3 --boundaries 1600,3200,4800 --out DIR/zpos_concat.npz
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import tifffile
from skimage.measure import block_reduce

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.benchmarks.synthetic_zstack import save_caiman_memmap, save_zstack_tiff
from tests.benchmarks.bruker_io import load_bruker_zstack


def _load_tiff_downsampled(path, factor, chunk=400):
    out = []
    with tifffile.TiffFile(path) as tf:
        pages = tf.pages
        n = len(pages)
        for i in range(0, n, chunk):
            batch = np.stack([pages[j].asarray() for j in range(i, min(i + chunk, n))]).astype(
                np.float32
            )
            if factor > 1:
                batch = block_reduce(batch, (1, factor, factor), np.mean).astype(np.float32)
            out.append(batch)
    return np.concatenate(out, 0)


def run_synthetic(zseries, downsample, seeds, out_dir):
    from tests.benchmarks.benchmark_zpos_methods import run_case

    vol, _ = load_bruker_zstack(zseries, channel=2, downsample=downsample)
    stats = {"caiman": {"r": [], "rmse": []}, "suite2p": {"r": [], "rmse": []}}
    for s in range(seeds):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_case(
                vol,
                "rigid",
                3.0,
                8,
                200,
                None,
                xy_amplitude=1.0,
                deform_amp=0.5,
                tmp_dir=Path(tmp),
                seed=s + 1,
            )
        for m in ("caiman", "suite2p"):
            stats[m]["r"].append(res[m]["r"])
            stats[m]["rmse"].append(res[m]["rmse_planes"])
        print(
            f"seed {s+1}: caiman r={res['caiman']['r']:.3f} rmse={res['caiman']['rmse_planes']:.3f} | "
            f"suite2p r={res['suite2p']['r']:.3f} rmse={res['suite2p']['rmse_planes']:.3f}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "zpos_synthetic.json").write_text(json.dumps(stats, indent=2))
    for m in ("caiman", "suite2p"):
        print(
            f"{m}: r={np.mean(stats[m]['r']):.3f}±{np.std(stats[m]['r']):.3f}  "
            f"rmse={np.mean(stats[m]['rmse']):.3f}±{np.std(stats[m]['rmse']):.3f}"
        )


def _compare_methods(movie, vol, boundaries, out_path):
    from modules.compute_zcorr import compute_zcorrel, compute_zcorrel_suite2p

    if vol.shape[1:] != movie.shape[1:]:
        # crop to common dims (rounding differences in downsample)
        h = min(vol.shape[1], movie.shape[1])
        w = min(vol.shape[2], movie.shape[2])
        vol = vol[:, :h, :w]
        movie = movie[:, :h, :w]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        save_zstack_tiff(vol, tmp / "z.tif")
        dd = tmp / "b" / "i"
        dd.mkdir(parents=True)
        mp = save_caiman_memmap(movie, dd)
        print("running compute_zcorrel...")
        zc = compute_zcorrel(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)
        print("running compute_zcorrel_suite2p...")
        zs = compute_zcorrel_suite2p(tmp / "z.tif", mp, smooth_sigma=3)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bnds = (
        np.array([int(b) for b in boundaries], dtype=int) if boundaries else np.array([], dtype=int)
    )
    np.savez(
        out_path,
        zpos_caiman=zc["zpos"].astype(float),
        zpos_suite2p=zs["zpos"].astype(float),
        boundaries=bnds,
    )
    zc_j = int(np.sum(np.abs(np.diff(zc["zpos"].astype(int))) >= 2))
    zs_j = int(np.sum(np.abs(np.diff(zs["zpos"].astype(int))) >= 2))
    print(
        f"Wrote {out_path}: ≥2-plane jumps caiman={zc_j} suite2p={zs_j}, "
        f"agreement r={np.corrcoef(zc['zpos'], zs['zpos'])[0,1]:.3f}"
    )


def run_real(mcorr_tiff, zseries, downsample, boundaries, out_path):
    print(f"Loading + downsampling movie {mcorr_tiff} (factor {downsample})...")
    movie = _load_tiff_downsampled(mcorr_tiff, downsample)
    print(f"movie {movie.shape}")
    vol, _ = load_bruker_zstack(zseries, channel=2, downsample=downsample)
    _compare_methods(movie, vol, boundaries, out_path)


def run_concat(tseries_dirs, zseries, downsample, out_path):
    """Concatenate several raw TSeries (downsampled) and compare z-pos methods.

    No NoRMCorre: compute_zcorrel does its own FOV registration, and the point is
    to expose z-pos behaviour at the session boundaries (where concatenation
    introduces abrupt intensity steps).
    """
    from tests.benchmarks.bruker_io import load_bruker_tseries

    movies, bnds, total = [], [], 0
    for d in tseries_dirs:
        m = load_bruker_tseries(d, channel=2, downsample=downsample)
        print(f"  {Path(d).name}: {m.shape}")
        total += m.shape[0]
        bnds.append(total)
        movies.append(m)
    movie = np.concatenate(movies, 0)
    bnds = bnds[:-1]  # internal session boundaries only
    print(f"concatenated {movie.shape}, boundaries {bnds}")
    vol, _ = load_bruker_zstack(zseries, channel=2, downsample=downsample)
    _compare_methods(movie, vol, bnds, out_path)


def _mcorr_session(movie, dview, work_dir):
    """Run production-parameter NoRMCorre (pw_rigid) on one session's movie.

    Returns the motion-corrected movie (T, H, W) as float32. Uses the exact
    params from ``pipeline/configs/config_template_cnmf.json`` (strides 36,
    overlaps 24, max_shifts 12, max_deviation_rigid 6, border_nan="copy",
    pw_rigid=True) so the edge artifacts match production output.
    """
    import caiman as cm
    from caiman.motion_correction import MotionCorrect
    from caiman.source_extraction.cnmf import params as cnmf_params

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    fname = str(work_dir / "sess.tif")
    tifffile.imwrite(fname, movie.astype(np.float32))
    opts = cnmf_params.CNMFParams(
        params_dict={
            "strides": (36, 36),
            "overlaps": (24, 24),
            "max_shifts": (12, 12),
            "max_deviation_rigid": 6,
            "border_nan": "copy",
            "pw_rigid": True,
        }
    )
    mc = MotionCorrect([fname], dview=dview, **opts.get_group("motion"))
    mc.motion_correct(save_movie=True)
    m = np.asarray(cm.load(mc.mmap_file), dtype=np.float32)
    # Clean up the on-disk products (the raw session tif + caiman memmaps).
    for f in [fname] + list(mc.mmap_file):
        try:
            Path(f).unlink()
        except OSError:
            pass
    return m


def run_concat_mcorr(tseries_dirs, zseries, downsample, out_path, work_dir):
    """Full-res NoRMCorre per session, then downsample+concat and compare z-pos.

    This is the production-faithful version of ``run_concat``: each session is
    motion-corrected at full resolution with the pipeline's NoRMCorre params
    (real mcorr edge artifacts), downsampled, and concatenated. Exposes both the
    real mcorr behaviour (where phasecorr latches to the deepest plane) and the
    session-boundary steps.
    """
    import caiman as cm
    from tests.benchmarks.bruker_io import load_bruker_tseries

    work_dir = Path(work_dir)
    c, dview, n_processes = cm.cluster.setup_cluster(
        backend="multiprocessing", n_processes=None, single_thread=False
    )
    try:
        movies, bnds, total = [], [], 0
        for d in tseries_dirs:
            full = load_bruker_tseries(d, channel=2, downsample=1)
            print(f"  {Path(d).name}: loaded {full.shape}, running NoRMCorre...", flush=True)
            mcorr = _mcorr_session(full, dview, work_dir / Path(d).name)
            del full
            if downsample > 1:
                mcorr = block_reduce(mcorr, (1, downsample, downsample), np.mean).astype(np.float32)
            print(f"    mcorr'd + downsampled -> {mcorr.shape}", flush=True)
            total += mcorr.shape[0]
            bnds.append(total)
            movies.append(mcorr)
    finally:
        cm.stop_server(dview=dview)
    movie = np.concatenate(movies, 0)
    del movies
    bnds = bnds[:-1]  # internal session boundaries only
    print(f"concatenated (mcorr'd) {movie.shape}, boundaries {bnds}", flush=True)
    vol, _ = load_bruker_zstack(zseries, channel=2, downsample=downsample)
    _compare_methods(movie, vol, bnds, out_path)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    ps = sub.add_parser("synthetic")
    ps.add_argument("--real-zstack", type=Path, required=True)
    ps.add_argument("--downsample", type=int, default=4)
    ps.add_argument("--seeds", type=int, default=8)
    ps.add_argument("--out", type=Path, required=True)
    pr = sub.add_parser("real")
    pr.add_argument("--mcorr-tiff", type=Path, required=True)
    pr.add_argument("--zseries", type=Path, required=True)
    pr.add_argument("--downsample", type=int, default=3)
    pr.add_argument("--boundaries", type=str, default="")
    pr.add_argument("--out", type=Path, required=True)
    pc = sub.add_parser("concat")
    pc.add_argument("--tseries", type=str, required=True, help="comma-separated TSeries dirs")
    pc.add_argument("--zseries", type=Path, required=True)
    pc.add_argument("--downsample", type=int, default=3)
    pc.add_argument("--out", type=Path, required=True)
    pcm = sub.add_parser("concat-mcorr")
    pcm.add_argument("--tseries", type=str, required=True, help="comma-separated TSeries dirs")
    pcm.add_argument("--zseries", type=Path, required=True)
    pcm.add_argument("--downsample", type=int, default=3)
    pcm.add_argument("--out", type=Path, required=True)
    pcm.add_argument(
        "--work-dir", type=Path, default=Path(tempfile.gettempdir()) / "concat_mcorr_work"
    )
    args = p.parse_args()

    if args.mode == "synthetic":
        run_synthetic(args.real_zstack, args.downsample, args.seeds, args.out)
    elif args.mode == "real":
        bnds = [int(x) for x in args.boundaries.split(",") if x.strip()]
        run_real(args.mcorr_tiff, args.zseries, args.downsample, bnds, args.out)
    elif args.mode == "concat-mcorr":
        dirs = [d for d in args.tseries.split(",") if d.strip()]
        run_concat_mcorr(dirs, args.zseries, args.downsample, args.out, args.work_dir)
    else:
        dirs = [d for d in args.tseries.split(",") if d.strip()]
        run_concat(dirs, args.zseries, args.downsample, args.out)


if __name__ == "__main__":
    main()
