"""Compare the pipeline outputs read by the Matlab analysis (Analysis_2P) between two exports.

Checks what analyze_2p_with_Beh_func.m loads: Suite2p Fall.mat (F, Fneu, iscell, stat, ops.zpos,
ops.meanImg, ops.nframes), results_caiman.mat, the F_anat_non_rigid_T_*_Y_*_X_*.tiff movie and the
shifted z-stack, plus z_correlation.npz (the source of ops.zpos). Also lists files present in only
one export.

Usage
-----
    pixi run python validation/compat_check.py <export_old> <export_new> [--zstack-old F --zstack-new F]
        [--out result.json]
"""

import argparse
import json
from pathlib import Path

import numpy as np
import tifffile
from scipy.io import loadmat


def cmp(a, b):
    """Summary of how two arrays differ (shape, dtype, exact equality, max |diff|, corr)."""
    a, b = np.asarray(a), np.asarray(b)
    out = {"shape": [list(a.shape), list(b.shape)], "dtype": [str(a.dtype), str(b.dtype)]}
    if a.shape != b.shape:
        out["equal"] = False
        return out
    out["equal"] = bool(np.array_equal(a, b))
    if not out["equal"] and a.size and np.issubdtype(a.dtype, np.number):
        d = np.abs(a.astype(np.float64) - b.astype(np.float64))
        out["max_abs_diff"] = float(d.max())
        out["frac_elements_differ"] = float(np.mean(d > 0))
        if a.std() > 0 and b.std() > 0:
            out["corr"] = float(np.corrcoef(a.ravel().astype(np.float64), b.ravel().astype(np.float64))[0, 1])
    return out


def find(export, pattern):
    hits = sorted(export.rglob(pattern))
    return hits[0] if hits else None


def stat_pixels(stat):
    return [(np.asarray(s.ypix).ravel(), np.asarray(s.xpix).ravel(), np.asarray(s.lam).ravel())
            for s in np.asarray(stat).ravel()]


def check_fall(fa, fb):
    a = loadmat(fa, squeeze_me=True, struct_as_record=False)
    b = loadmat(fb, squeeze_me=True, struct_as_record=False)
    R = {"keys_only_old": sorted(set(a) - set(b) - {"__header__", "__version__", "__globals__"}),
         "keys_only_new": sorted(set(b) - set(a) - {"__header__", "__version__", "__globals__"})}
    for k in ("F", "Fneu", "iscell", "spks"):
        if k in a and k in b:
            R[k] = cmp(a[k], b[k])
    oa, ob = a["ops"], b["ops"]
    for k in ("zpos", "meanImg", "nframes"):
        R[f"ops.{k}"] = cmp(getattr(oa, k, np.nan), getattr(ob, k, np.nan)) if hasattr(oa, k) or hasattr(ob, k) else "absent"
    fa_ops, fb_ops = set(oa._fieldnames), set(ob._fieldnames)
    R["ops_fields_only_old"] = sorted(fa_ops - fb_ops)
    R["ops_fields_only_new"] = sorted(fb_ops - fa_ops)
    sa, sb = stat_pixels(a["stat"]), stat_pixels(b["stat"])
    R["stat_n"] = [len(sa), len(sb)]
    if len(sa) == len(sb):
        R["stat_pixels_equal"] = all(np.array_equal(x[0], y[0]) and np.array_equal(x[1], y[1]) for x, y in zip(sa, sb))
        R["stat_lam_max_abs_diff"] = float(max(np.abs(x[2] - y[2]).max() if len(x[2]) == len(y[2]) else np.inf
                                               for x, y in zip(sa, sb)))
    return R


def check_caiman(fa, fb):
    a, b = loadmat(fa), loadmat(fb)
    keys = sorted((set(a) | set(b)) - {"__header__", "__version__", "__globals__"})
    R = {"keys_only_old": sorted(set(keys) - set(b)), "keys_only_new": sorted(set(keys) - set(a))}
    for k in keys:
        if k in a and k in b:
            va, vb = a[k], b[k]
            if hasattr(va, "toarray"):
                va = va.toarray()
            if hasattr(vb, "toarray"):
                vb = vb.toarray()
            try:
                R[k] = cmp(va, vb)
            except Exception as e:  # object arrays etc.
                R[k] = f"not compared ({type(e).__name__})"
    return R


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--zstack-old", type=Path, default=None)
    ap.add_argument("--zstack-new", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    R = {"old": str(args.old), "new": str(args.new)}

    files = lambda e: {str(p.relative_to(e)) for p in e.rglob("*") if p.is_file() and "/mm/" not in str(p)}  # noqa: E731
    fo, fn = files(args.old), files(args.new)
    R["files_only_old"] = sorted(f for f in fo - fn if not f.endswith((".mmap", ".npy", ".runfile", ".pickle")))
    R["files_only_new"] = sorted(f for f in fn - fo if not f.endswith((".mmap", ".npy", ".runfile", ".pickle")))

    za, zb = find(args.old, "z_correlation.npz"), find(args.new, "z_correlation.npz")
    if za and zb:
        a, b = np.load(za), np.load(zb)
        R["z_correlation"] = {k: cmp(a[k], b[k]) for k in set(a.files) & set(b.files)}

    fa, fb = find(args.old, "Fall.mat"), find(args.new, "Fall.mat")
    if fa and fb:
        R["Fall"] = check_fall(fa, fb)

    ca, cb = find(args.old, "results_caiman.mat"), find(args.new, "results_caiman.mat")
    if ca and cb:
        R["results_caiman"] = check_caiman(ca, cb)

    ta, tb = find(args.old, "F_anat_non_rigid_T_*.tiff"), find(args.new, "F_anat_non_rigid_T_*.tiff")
    R["F_anat_names"] = [ta.name if ta else None, tb.name if tb else None]
    if ta and tb:
        R["F_anat"] = cmp(tifffile.imread(ta), tifffile.imread(tb))

    if args.zstack_old and args.zstack_new:
        pages = lambda f: np.stack([p.asarray() for p in tifffile.TiffFile(f).pages])  # noqa: E731
        R["zstack_shifted"] = cmp(pages(args.zstack_old), pages(args.zstack_new))

    print(json.dumps(R, indent=1))
    if args.out:
        args.out.write_text(json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
