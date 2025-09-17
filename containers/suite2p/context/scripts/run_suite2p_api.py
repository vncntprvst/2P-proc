#!/usr/bin/env python3
"""
Run Suite2p detection and extraction via the Python API for a single plane,
using an existing ops.npy. This provides tighter control than `python -m suite2p`.

Behavior:
- Loads ops from --ops
- Validates a single input type (HDF5, TIFF, or existing BIN)
- If input is HDF5 or TIFF, converts to Suite2p binary (.bin) using suite2p.io helpers
- If input is existing BIN, verifies dims and links/copies into plane directory
- Runs detection and extraction via the Suite2p API
- Optionally runs classification (iscell.npy) and deconvolution (spks.npy)
- Saves outputs (ops.npy, stat.npy, F.npy, Fneu.npy, optional spks/iscell) to suite2p/plane{N}

Notes:
- Expects ops['save_path0'] to be the export folder (created by make_ops.py)
- Respects ops['spikedetect'] for optional deconvolution
- Required ops keys: 'Ly', 'Lx', 'fs' (and 'reg_file' if input is binary)

CLI additions:
- --input to force input type (auto|tiff|h5|bin)
- --plane to choose plane index (default 0)
- --no-binning-patch to disable the per-run binning monkey-patch
"""
import argparse
import os
import sys
import time
import numpy as np

import suite2p
from pathlib import Path
import shutil
from typing import Optional, List
import json
from math import floor


def ensure_plane_dirs(ops: dict, plane: int = 0) -> str:
    """Ensure Suite2p plane directory exists and update standard ops paths.

    Parameters
    - ops: Suite2p ops dict (must include 'save_path0')
    - plane: plane index to use (default 0)

    Returns
    - plane_dir (str): absolute path to suite2p/plane{plane}
    """
    save_path0 = ops.get("save_path0")
    if not save_path0:
        raise ValueError("ops['save_path0'] is required")
    base = Path(save_path0).expanduser().resolve()
    plane_dir = base / "suite2p" / f"plane{plane}"
    plane_dir.mkdir(parents=True, exist_ok=True)
    # Fill in standard paths used by Suite2p save utils
    ops["save_path0"] = str(base)
    ops["save_path"] = str(plane_dir)
    ops["ops_path"] = str(plane_dir / "ops.npy")
    ops["save_folder"] = "."
    return str(plane_dir)

def _normalize_ops_paths(ops: dict) -> dict:
    """Normalize relevant paths inside ops to absolute paths.

    Keys handled: save_path0, reg_file, data_path, h5py, h5list, tiff_list.
    """
    if ops.get("save_path0"):
        ops["save_path0"] = str(Path(ops["save_path0"]).expanduser().resolve())
    if ops.get("reg_file"):
        ops["reg_file"] = str(Path(ops["reg_file"]).expanduser().resolve())

    # data_path can be str or list of dirs; normalize to list of absolute dirs
    dp = ops.get("data_path")
    if isinstance(dp, (list, tuple)):
        ops["data_path"] = [str(Path(p).expanduser().resolve()) for p in dp]
    elif isinstance(dp, str) and dp:
        ops["data_path"] = [str(Path(dp).expanduser().resolve())]

    # h5py can be str or list; Suite2p typically expects a list of files
    hp = ops.get("h5py")
    if isinstance(hp, (list, tuple)):
        ops["h5py"] = [str(Path(p).expanduser().resolve()) for p in hp]
    elif isinstance(hp, str) and hp:
        ops["h5py"] = [str(Path(hp).expanduser().resolve())]

    # h5list if present
    if isinstance(ops.get("h5list"), (list, tuple)):
        ops["h5list"] = [str(Path(p).expanduser().resolve()) for p in ops["h5list"]]

    # TIFF handling: ensure tiff_list is list of filenames and data_path points to their directory
    tl = ops.get("tiff_list")
    if isinstance(tl, (list, tuple)):
        # if any entries contain directories, move that part into data_path and keep basenames
        abs_files: List[Path] = [Path(p).expanduser() for p in tl]
        # If data_path is not provided but tiff_list has absolute paths, derive it from the first file
        if not ops.get("data_path") and any(p.is_absolute() for p in abs_files):
            base_dir = str(abs_files[0].resolve().parent)
            ops["data_path"] = [base_dir]
        # Always store basenames in tiff_list as Suite2p joins with data_path
        tiff_names = [p.name for p in abs_files]
        # Prefer mcorr_movie.tiff over mcorr_u8.tiff when both exist
        if "mcorr_u8.tiff" in tiff_names and "mcorr_movie.tiff" not in tiff_names:
            # If mcorr_movie.tiff exists on disk in data_path, swap it in
            dp0 = ops.get("data_path", [None])[0]
            if dp0 is not None:
                mmovie = Path(dp0) / "mcorr_movie.tiff"
                if mmovie.exists():
                    tiff_names = ["mcorr_movie.tiff" if n == "mcorr_u8.tiff" else n for n in tiff_names]
        ops["tiff_list"] = tiff_names
    return ops


def _determine_input_kind(ops: dict, forced: Optional[str] = None) -> str:
    """Return one of {'h5','tiff','bin','none'} based on ops and optional forced selection.

    Raises ValueError if multiple inputs found or conflict with forced.
    """
    # h5py is expected to be a list after normalization
    has_h5 = (isinstance(ops.get("h5py"), (list, tuple)) and len(ops.get("h5py")) > 0) \
             or len(ops.get("h5list", [])) > 0 or ops.get("input_format") == "h5"
    has_tiff = bool(ops.get("tiff_list")) or ops.get("input_format") == "tiff"
    has_bin = bool(ops.get("reg_file")) and Path(str(ops.get("reg_file"))).exists()
    kinds = [k for k, f in (("h5", has_h5), ("tiff", has_tiff), ("bin", has_bin)) if f]
    if forced and forced != "auto":
        if forced not in {"h5", "tiff", "bin"}:
            raise ValueError(f"Invalid --input '{forced}' (expected auto|tiff|h5|bin)")
        # validate forced kind exists
        if forced == "h5" and not has_h5:
            raise ValueError("--input=h5 specified but no h5py/h5list provided in ops")
        if forced == "tiff" and not has_tiff:
            raise ValueError("--input=tiff specified but no tiff_list provided in ops")
        if forced == "bin" and not has_bin:
            raise ValueError("--input=bin specified but ops['reg_file'] is missing or invalid")
        # ensure exclusivity
        if len(kinds) > 1:
            raise ValueError(f"Multiple input types specified in ops: {kinds}. Provide exactly one.")
        return forced
    # auto mode
    if len(kinds) == 0:
        return "none"
    if len(kinds) > 1:
        raise ValueError(f"Multiple input types specified in ops: {kinds}. Provide exactly one.")
    return kinds[0]


# --- Monkey-patch: make Suite2p binning carry leftovers across chunks ---
# Goal: Ensure total binned frames ~= floor(n_good_frames / bin_size),
# avoiding per-500-chunk remainders being dropped repeatedly.
_ORIG_BIN_MOVIE = None  # saved original method

def _install_bin_movie_patch(verbose: bool = True) -> None:
    """Patch suite2p.io.BinaryFile.bin_movie to use chunk sizes divisible by
    bin_size and to carry remainders across chunks. Safe no-op if already patched.

    This affects only the current Python process.
    """
    global _ORIG_BIN_MOVIE
    try:
        BF = suite2p.io.BinaryFile
    except Exception:
        return
    # Idempotent
    if getattr(BF, "_analysis2p_binpatch", False):
        return

    _ORIG_BIN_MOVIE = BF.bin_movie

    def _patched_bin_movie(self, bin_size: int = 1, bad_frames=None, y_range=None, x_range=None, multidim: bool = False, **kwargs):
        # Defer to original if multidim requested (preserve original behavior)
        if multidim:
            return _ORIG_BIN_MOVIE(self, bin_size=bin_size, bad_frames=bad_frames, y_range=y_range, x_range=x_range, multidim=multidim, **kwargs)

        # Validate bin_size
        try:
            bsz = int(bin_size)
        except Exception:
            bsz = 1
        bsz = max(1, bsz)

        # Good frames mask
        n_total = int(getattr(self, 'n_frames', 0))
        if bad_frames is None:
            good = np.ones(n_total, dtype=bool)
        else:
            bad = np.asarray(bad_frames, dtype=bool)
            if bad.size != n_total:
                good = np.ones(n_total, dtype=bool)
            else:
                good = ~bad

        # Pre-compute output size (floor division across ALL good frames)
        n_good = int(good.sum())
        n_bins_total = int(n_good // bsz)
        Ly_full = int(getattr(self, 'Ly', 0))
        Lx_full = int(getattr(self, 'Lx', 0))
        # Apply cropping ranges to determine output spatial dims
        if y_range is None:
            y0, y1 = 0, Ly_full
        else:
            y0, y1 = int(y_range[0]), int(y_range[1])
            y0 = max(0, min(y0, Ly_full))
            y1 = max(y0, min(y1, Ly_full))
        if x_range is None:
            x0, x1 = 0, Lx_full
        else:
            x0, x1 = int(x_range[0]), int(x_range[1])
            x0 = max(0, min(x0, Lx_full))
            x1 = max(x0, min(x1, Lx_full))
        Ly = y1 - y0
        Lx = x1 - x0
        if n_bins_total <= 0 or Ly == 0 or Lx == 0:
            return np.zeros((0, Ly, Lx), dtype=np.float32)

        out = np.empty((n_bins_total, Ly, Lx), dtype=np.float32)

        # Choose a chunk size that is a multiple of bin_size (<= 500)
        base_chunk = 500
        chunk = (base_chunk // bsz) * bsz
        if chunk < bsz:
            chunk = bsz

        idx_out = 0
        carry = None  # leftover frames from previous iteration

        # Iterate over the whole file in fixed chunks; apply good mask per-chunk
        for start in range(0, n_total, chunk):
            stop = min(start + chunk, n_total)
            # Load frames (shape expected: (T, Ly, Lx))
            block = self.file[start:stop]
            if block.size == 0:
                continue
            # Crop spatially if requested
            if (y0 != 0 or y1 != Ly_full) or (x0 != 0 or x1 != Lx_full):
                block = block[:, y0:y1, x0:x1]
            # Apply good mask for this interval
            if good[start:stop].all():
                data = block
            else:
                data = block[good[start:stop]]

            if data.shape[0] == 0:
                continue

            # Concatenate with carry from prior chunk
            if carry is not None and carry.shape[0] > 0:
                data = np.concatenate((carry, data), axis=0)

            # Form as many full bins as possible from data
            n_full = (data.shape[0] // bsz) * bsz
            if n_full == 0:
                # Not enough frames to make a full bin yet; carry them
                carry = data
                continue

            # Compute means across contiguous groups of bsz frames
            # Ensure float32 math for consistency with Suite2p
            chunk_bins = data[:n_full].astype(np.float32).reshape(-1, bsz, Ly, Lx).mean(axis=1)
            nb = chunk_bins.shape[0]
            out[idx_out:idx_out + nb] = chunk_bins
            idx_out += nb

            # Keep leftover frames for next iteration
            carry = data[n_full:]

        # We intentionally drop any final leftover < bsz, matching floor(n_good/bsz)
        if idx_out != n_bins_total:
            # Trim in rare cases where mask interactions were unexpected
            out = out[:idx_out]

        return out

    # Install
    BF.bin_movie = _patched_bin_movie
    setattr(BF, "_analysis2p_binpatch", True)
    if verbose:
        print("[run_suite2p_api] Patched Suite2p BinaryFile.bin_movie (carry leftovers; chunk multiple of bin_size)")


def _validate_ops(ops: dict, input_kind: str) -> None:
    """Validate required ops keys prior to running detection/extraction.

    Required always: Ly, Lx, fs
    Additionally for binary input: reg_file must exist
    """
    missing = [k for k in ("Ly", "Lx", "fs") if k not in ops]
    if missing:
        raise ValueError(f"Missing required ops keys: {missing}")
    if input_kind == "bin":
        reg = ops.get("reg_file")
        if not reg or not Path(str(reg)).is_file():
            raise FileNotFoundError(f"Binary input selected but ops['reg_file'] invalid: {reg}")


def _safe_remove(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def convert_to_binary(ops: dict, input_kind: str) -> dict:
    """Convert input to Suite2p binary and return updated ops.

    Supports exactly one input type per run: HDF5, TIFF, or existing binary.
    - HDF5: uses suite2p.io.h5py_to_binary(ops)
    - TIFF: uses suite2p.io.tiff_to_binary(ops)
    - Binary: verifies file, infers nframes, and links/copies into plane dir

    Returns
    - Updated ops with ops['reg_file'] pointing to plane dir data.bin
    """
    ops = _normalize_ops_paths(dict(ops))
    plane_dir = Path(ops.get("save_path", ops.get("save_path0", "."))).expanduser().resolve()
    plane_dir.mkdir(parents=True, exist_ok=True)

    if input_kind == "h5":
        print("[run_suite2p_api] Converting HDF5 to binary with suite2p.io.h5py_to_binary …")
        try:
            ops2 = suite2p.io.h5py_to_binary(ops)
            ops2 = _normalize_ops_paths(ops2)
            print(f"[run_suite2p_api] H5->BIN done: reg_file={ops2.get('reg_file')}")
            return ops2
        except Exception as e:
            _safe_remove(plane_dir / "data.bin")
            print(f"[run_suite2p_api] H5->BIN failed: {e}", file=sys.stderr)
            raise

    if input_kind == "tiff":
        print("[run_suite2p_api] Converting TIFF to binary with suite2p.io.tiff_to_binary …")
        try:
            ops2 = suite2p.io.tiff_to_binary(ops)
            ops2 = _normalize_ops_paths(ops2)
            print(f"[run_suite2p_api] TIFF->BIN done: reg_file={ops2.get('reg_file')}")
            return ops2
        except Exception as e:
            _safe_remove(plane_dir / "data.bin")
            print(f"[run_suite2p_api] TIFF->BIN failed: {e}", file=sys.stderr)
            raise

    if input_kind == "bin":
        reg_file = ops.get("reg_file")
        if not reg_file or not Path(reg_file).is_file():
            raise FileNotFoundError(f"No binary found: ops['reg_file']={reg_file}. This Suite2p API script is designed to work with motion-corrected files.")
        if "Ly" not in ops or "Lx" not in ops:
            raise ValueError("Ly and Lx must be present in ops when providing an existing binary (reg_file).")
        Ly, Lx = int(ops["Ly"]), int(ops["Lx"])

        # Warn if dtype atypical; BinaryFile does int16 frame size math
        if str(ops.get("dtype", "int16")).lower() not in ("int16", "np.int16", "<i2", "i2"):
            print("[run_suite2p_api] Warning: ops['dtype'] not int16; Suite2p BinaryFile assumes int16 layout.")

        reg_path = Path(reg_file).expanduser().resolve()
        # Infer nframes using Suite2p BinaryFile
        with suite2p.io.BinaryFile(Ly=Ly, Lx=Lx, filename=str(reg_path)) as bf:
            ops["nframes"] = int(bf.n_frames)

        # Create/overwrite plane_dir/data.bin using Suite2p BinaryFile API
        target_bin = plane_dir / "data.bin"
        tmp_bin = plane_dir / "data.bin.tmp"
        # Ensure we start fresh
        for p in (target_bin, tmp_bin):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        try:
            with suite2p.io.BinaryFile(Ly=Ly, Lx=Lx, filename=str(reg_path)) as src:
                nframes = src.n_frames
                ops["nframes"] = int(nframes)
                with suite2p.io.BinaryFile(Ly=Ly, Lx=Lx, filename=str(tmp_bin), n_frames=nframes, dtype="int16") as dst:
                    # copy in batches to limit memory
                    batch = 1000
                    copied = 0
                    for start in range(0, nframes, batch):
                        stop = min(start + batch, nframes)
                        block = src.file[start:stop]
                        if block.dtype != np.int16:
                            block = np.floor(block).astype(np.int16)
                        dst.file[start:stop] = block
                        copied += (stop - start)
            # atomic rename into place
            tmp_bin.replace(target_bin)
            print(f"[run_suite2p_api] Wrote BIN to {target_bin} using Suite2p BinaryFile (nframes={nframes})")
        except Exception:
            _safe_remove(tmp_bin)
            raise

        ops["reg_file"] = str(target_bin)
        print(f"[run_suite2p_api] Using BIN: reg_file={ops['reg_file']}, nframes={ops.get('nframes')}")
        return ops

    # none: nothing to convert
    print("[run_suite2p_api] No input detected (need h5/tiff/reg_file).")
    return ops


def compute_bin_size(ops: dict) -> int:
    nbinned = max(1, int(ops.get("nbinned", 1)))
    nframes = int(ops.get("nframes", 0))
    tau = float(ops.get("tau", 1.0))
    fs = float(ops.get("fs", 1.0))
    return int(max(1, (nframes // nbinned) if nframes > 0 else 1, round(tau * fs)))


def main():
    ap = argparse.ArgumentParser(description="Run Suite2p detection+extraction via API")
    ap.add_argument("--ops", required=True, help="Path to ops.npy")
    ap.add_argument("--classify", type=int, default=1, help="Run ROI classification and save iscell.npy (1/0)")
    ap.add_argument("--input", default="auto", choices=["auto", "tiff", "h5", "bin"], help="Force input type")
    ap.add_argument("--plane", type=int, default=0, help="Plane index (default 0)")
    ap.add_argument("--no-binning-patch", action="store_true", help="Disable binning monkey-patch (use Suite2p default chunked binning)")
    args = ap.parse_args()
    
    print(f"[run_suite2p_api] suite2p version: {suite2p.version}")

    # Load ops
    ops_path = os.path.abspath(args.ops)
    if not os.path.isfile(ops_path):
        print(f"ops file not found: {ops_path}", file=sys.stderr)
        return 2
    ops = np.load(ops_path, allow_pickle=True).item()
    # Normalize important paths first
    ops = _normalize_ops_paths(ops)

    plane_dir = ensure_plane_dirs(ops, plane=args.plane)

    # Normalize binning defaults to match Suite2p GUI behavior:
    # bin_frames = round(tau * fs)
    # nbinned = nframes // bin_frames
    fs = float(ops.get("fs", 1.0))
    tau = float(ops.get("tau", 1.0))
    if "bin_frames" not in ops or int(ops.get("bin_frames", 0)) < 1:
        ops["bin_frames"] = max(1, int(round(tau * fs)))
    # Always ensure nbinned is consistent with bin_frames if missing/invalid
    if "nbinned" not in ops or int(ops.get("nbinned", 0)) < 1:
        nframes = int(ops.get("nframes", 0))
        if nframes > 0:
            ops["nbinned"] = max(1, nframes // int(ops["bin_frames"]))
        else:
            ops["nbinned"] = 1

    # Determine and convert input to S2P binary format
    try:
        kind = _determine_input_kind(ops, forced=args.input)
    except ValueError as e:
        print(f"[run_suite2p_api] Input selection error: {e}", file=sys.stderr)
        return 3
    # Validate minimal ops before conversion (dims needed for bin inference case)
    try:
        _validate_ops(ops, input_kind=kind)
    except Exception as e:
        print(f"[run_suite2p_api] Ops validation error: {e}", file=sys.stderr)
        return 3
    ops = convert_to_binary(ops, input_kind=kind)

    # Ensure reg_file exists
    reg_file = ops.get("reg_file")
    if not reg_file or not os.path.isfile(reg_file):
        # Some converters write into save_path0/suite2p/plane0/data.bin
        fallback = os.path.join(plane_dir, "data.bin")
        if os.path.isfile(fallback):
            reg_file = fallback
            ops["reg_file"] = reg_file
        else:
            raise FileNotFoundError(f"No binary found: ops['reg_file']={reg_file}")

    Ly, Lx = int(ops["Ly"]), int(ops["Lx"])
    ops["yrange"] = ops.get("yrange", [0, Ly])
    ops["xrange"] = ops.get("xrange", [0, Lx])

    # Debug: print binning-related ops values and types to help diagnose mismatches
    try:
        print(
            "[run_suite2p_api] DEBUG ops: nframes={} ({}), fs={} ({}), nbinned={} ({}), bin_frames={} ({})".format(
                ops.get("nframes"), type(ops.get("nframes")),
                ops.get("fs"), type(ops.get("fs")),
                ops.get("nbinned"), type(ops.get("nbinned")),
                ops.get("bin_frames"), type(ops.get("bin_frames")),
            )
        )
    except Exception as _:
        print("[run_suite2p_api] DEBUG: failed to print ops dump")

    # # Also write a stable debug file into the plane dir so logs can be inspected later
    # try:
    #     dbg = {k: {"value": str(v), "type": str(type(v))} for k, v in ops.items()}
    #     with open(os.path.join(plane_dir, "ops_debug.json"), "w") as fo:
    #         json.dump(dbg, fo, indent=2)
    #     print(f"[run_suite2p_api] Wrote ops debug to {os.path.join(plane_dir, 'ops_debug.json')}")
    # except Exception:
    #     print("[run_suite2p_api] Could not write ops_debug.json")

    # Detection
    t0 = time.time()
    print("[run_suite2p_api] DETECTION …")
    # Optionally install binning monkey-patch so leftovers carry and chunks align to bin_size
    patch_enabled = not args.no_binning_patch
    if patch_enabled:
        try:
            _install_bin_movie_patch()
        except Exception:
            patch_enabled = False

    # Predict expected binned length (floor over all good frames)
    try:
        nframes = int(ops.get("nframes", 0))
        bin_size = compute_bin_size(ops)
        # Try to estimate number of bad frames if provided in ops
        bad = ops.get("badframes") or ops.get("bad_frames")
        if bad is not None:
            bad = np.asarray(bad, dtype=bool)
            n_good = int((~bad).sum()) if bad.size == nframes else nframes
        else:
            n_good = nframes
        exp_bins = n_good // max(1, bin_size)
        mode = "patched" if patch_enabled else "default"
        print(f"[run_suite2p_api] Expected binned frames ≈ {exp_bins} (mode={mode}, n_good={n_good}, bin_size={bin_size})")
    except Exception:
        pass

    # Use the built-in detect() to match Suite2p CLI behavior on binning and logging
    try:
        ops, stat = suite2p.detection.detect(ops=ops)
    except Exception as e:
        print(f"[run_suite2p_api] DETECTION failed: {e}", file=sys.stderr)
        return 4
    print(f"[run_suite2p_api] DETECTION done: {len(stat)} ROIs in {time.time()-t0:.2f}s")

    # Save intermediate
    np.save(os.path.join(plane_dir, "ops.npy"), ops)
    # Extraction
    if len(stat) > 0:
        print("[run_suite2p_api] EXTRACTION …")
        t1 = time.time()
        # Open binary for extraction
        try:
            with suite2p.io.BinaryFile(Ly=Ly, Lx=Lx, filename=ops["reg_file"]) as f_reg:
                stat, F, Fneu, F_chan2, Fneu_chan2 = suite2p.extraction.extraction_wrapper(
                    stat, f_reg, ops=ops
                )
        except Exception as e:
            print(f"[run_suite2p_api] EXTRACTION failed: {e}", file=sys.stderr)
            return 5
        # Save outputs
        np.save(os.path.join(plane_dir, "stat.npy"), stat)
        np.save(os.path.join(plane_dir, "F.npy"), F)
        np.save(os.path.join(plane_dir, "Fneu.npy"), Fneu)
        if len(F_chan2) != 0:
            np.save(os.path.join(plane_dir, "F_chan2.npy"), F_chan2)
        if len(Fneu_chan2) != 0:
            np.save(os.path.join(plane_dir, "Fneu_chan2.npy"), Fneu_chan2)
        print(f"[run_suite2p_api] EXTRACTION done in {time.time()-t1:.2f}s (stat={len(stat)}, F.shape={getattr(F, 'shape', None)})")

        # Optional classification (iscell.npy)
        if args.classify:
            try:
                # Suite2p classify() requires a classifier file; try user then builtin
                from suite2p.classification import classify
                clf_path = None
                try:
                    from suite2p.classification import user_classfile, builtin_classfile
                    # Prefer user classifier if it exists
                    for cand in (user_classfile, builtin_classfile):
                        try:
                            p = Path(str(cand))
                            if p.exists():
                                clf_path = str(p)
                                break
                        except Exception:
                            continue
                except Exception:
                    # Fallback: derive builtin path relative to suite2p package
                    try:
                        pkg_dir = Path(suite2p.__file__).parent
                        alt = pkg_dir / "classifiers" / "classifier.npy"
                        if alt.exists():
                            clf_path = str(alt)
                    except Exception:
                        pass

                if clf_path is None:
                    raise RuntimeError("No Suite2p classifier file found (user or builtin)")

                from suite2p.detection.stats import roi_stats
                stat2 = roi_stats(
                    stat,
                    Ly,
                    Lx,
                    aspect=ops.get("aspect", None),
                    diameter=ops.get("diameter", None),
                    do_crop=ops.get("soma_crop", 1),
                )
                if len(stat2) == 0:
                    iscell = np.zeros((0, 2))
                else:
                    iscell = classify(stat=stat2, classfile=clf_path)
                np.save(os.path.join(plane_dir, "iscell.npy"), iscell)
                print("[run_suite2p_api] CLASSIFICATION saved iscell.npy")
            except Exception as e:
                print(f"[run_suite2p_api] Classification skipped: {e}")

        # Optional deconvolution
        if ops.get("spikedetect", False):
            try:
                print("[run_suite2p_api] DECONV …")
                # Preprocess + deconv
                dF = F - ops.get("neucoeff", 0.7) * Fneu
                dF = suite2p.extraction.preprocess(
                    F=dF,
                    baseline=ops.get("baseline", "maximin"),
                    win_baseline=ops.get("win_baseline", int(60 * ops.get("fs", 1.0))),
                    sig_baseline=ops.get("sig_baseline", 10.0),
                    fs=ops.get("fs", 1.0),
                    prctile_baseline=ops.get("prctile_baseline", 8),
                )
                spks = suite2p.extraction.oasis(
                    F=dF,
                    batch_size=ops.get("batch_size", 500),
                    tau=ops.get("tau", 1.0),
                    fs=ops.get("fs", 1.0),
                )
                np.save(os.path.join(plane_dir, "spks.npy"), spks)
                print(f"[run_suite2p_api] DECONV saved spks.npy (shape={getattr(spks, 'shape', None)})")
            except Exception as e:
                print(f"[run_suite2p_api] Deconv skipped: {e}")

        # Optional MATLAB save
        if ops.get("save_mat", 0):
            try:
                # Suite2p save_mat expects full arguments; populate optional arrays if missing
                from suite2p.io.save import save_mat
                iscell_path = os.path.join(plane_dir, "iscell.npy")
                spks_path = os.path.join(plane_dir, "spks.npy")
                iscell = np.load(iscell_path, allow_pickle=True) if os.path.isfile(iscell_path) else np.zeros((len(stat), 2))
                spks = np.load(spks_path, allow_pickle=True) if os.path.isfile(spks_path) else np.zeros_like(F)
                redcell = np.zeros((0, 2))
                # Force save paths to suite2p/plane{N} for MATLAB export only
                save_ops = dict(ops)
                save_ops["save_path"] = str(plane_dir)
                save_ops["save_path0"] = str(plane_dir)
                save_ops["save_folder"] = "."
                save_mat(save_ops, stat, F, Fneu, spks, iscell, redcell)
                print("[run_suite2p_api] Saved MATLAB outputs")
            except Exception as e:
                print(f"[run_suite2p_api] save_mat failed: {e}")



    # Done.
    # Cleanup: remove stray plane0 under export root (older save_mat behavior)
    try:
        export_root = Path(ops.get("save_path0", plane_dir)).expanduser().resolve()
        stray_plane = export_root / "plane0"
        target_plane = Path(plane_dir).expanduser().resolve()
        if stray_plane.is_dir() and stray_plane.resolve() != target_plane:
            shutil.rmtree(stray_plane)
            print(f"[run_suite2p_api] Removed stray directory: {stray_plane}")
    except Exception as e:
        print(f"[run_suite2p_api] Cleanup skipped: {e}")

    print("[run_suite2p_api] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
