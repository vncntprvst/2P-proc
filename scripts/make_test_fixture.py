"""Build a minimal Bruker-layout z-motion test fixture for a GitHub release asset.

The previous pipeline test data was cut from isosbestic recordings and is not a
good target for z-motion correction. This script carves a *small* fixture out of
a real functional session (default ``C57_O1M2/10022023``) that still runs through
motion correction + z-correction: one short, spatially-downsampled TSeries plus
its downsampled ZSeries reference stack, re-written in the Bruker per-frame
OME-TIFF layout the pipeline expects.

The goal is the smallest archive that still exercises the pipeline, so it can be
attached to a GitHub release and pulled by ``scripts/download_test_data.sh``.

Usage
-----
    python scripts/make_test_fixture.py \
        --src /home/wanglab/data/2P/C57_O1M2/10022023 \
        --out Mesmerize/test_data --downsample 4 --n-frames 150

Produces ``<out>/`` with the Bruker-named subfolders and a sibling
``<out>.tar.gz`` ready to upload.
"""

import argparse
import json
import sys
import tarfile
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.benchmarks.bruker_io import (  # noqa: E402
    _list_channel_tifs,
    _read_frame,
    _downscale,
    parse_z_focus_um,
)


def _write_bruker_folder(src_folder, dst_folder, channel, downsample, n_frames=None):
    """Downsample a Bruker folder's Ch{channel} frames into a fixture folder.

    Frames are re-written as single-page ``.ome.tif`` files keeping the original
    Bruker names (``{name}_Cycle00001_Ch{ch}_{i:06d}.ome.tif``); the XML sidecar
    is copied verbatim (z-positions and geometry stay valid under spatial
    downsampling).
    """
    src_folder = Path(src_folder)
    dst_folder = Path(dst_folder)
    dst_folder.mkdir(parents=True, exist_ok=True)

    files = _list_channel_tifs(src_folder, channel)
    if not files:
        raise FileNotFoundError(f"No Ch{channel} tifs in {src_folder}")
    if n_frames is not None:
        files = files[:n_frames]

    for f in files:
        frame = _downscale(_read_frame(f).astype(np.float32), downsample)
        out = dst_folder / Path(f).name
        tifffile.imwrite(out, frame.astype(np.uint16), photometric="minisblack")

    # Copy the XML sidecar so downstream z-position / geometry parsing still works.
    xml = src_folder / f"{src_folder.name}.xml"
    if xml.exists():
        (dst_folder / xml.name).write_bytes(xml.read_bytes())

    return len(files)


def main():
    p = argparse.ArgumentParser(description="Build a minimal z-motion pipeline test fixture")
    p.add_argument("--src", type=Path, default=Path("/home/wanglab/data/2P/C57_O1M2/10022023"))
    p.add_argument("--out", type=Path, default=Path("Mesmerize/test_data"))
    p.add_argument("--tseries", default="TSeries-10022023-1300-001")
    p.add_argument("--zstack", default="ZSeries-10022023-1300-004")
    p.add_argument("--channel", type=int, default=2)
    p.add_argument("--downsample", type=int, default=4, help="Spatial mean-pool factor")
    p.add_argument("--n-frames", type=int, default=150, help="TSeries frames to keep")
    p.add_argument("--no-tar", action="store_true", help="Skip building the .tar.gz")
    args = p.parse_args()

    out = args.out
    if out.exists():
        print(f"Removing existing {out} ...")
        import shutil

        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Building fixture from {args.src} (downsample {args.downsample}x)")
    n_t = _write_bruker_folder(
        args.src / args.tseries,
        out / args.tseries,
        args.channel,
        args.downsample,
        args.n_frames,
    )
    print(f"  TSeries: {n_t} frames -> {out / args.tseries}")
    n_z = _write_bruker_folder(
        args.src / args.zstack,
        out / args.zstack,
        args.channel,
        args.downsample,
        None,
    )
    print(f"  ZSeries: {n_z} planes -> {out / args.zstack}")

    z_um = parse_z_focus_um(args.src / args.zstack / f"{args.zstack}.xml")
    manifest = {
        "source": str(args.src),
        "tseries": args.tseries,
        "zstack": args.zstack,
        "channel": args.channel,
        "downsample": args.downsample,
        "n_frames": n_t,
        "n_planes": n_z,
        "z_um_range": [float(z_um.min()), float(z_um.max())] if len(z_um) else None,
        "note": "Minimal z-motion pipeline test fixture (real C57_O1M2 anatomy).",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (out / "README.md").write_text(
        "# z-motion test fixture\n\n"
        "Minimal real-anatomy fixture for the 2P z-motion benchmark and pipeline "
        "motion-correction test. Downsampled subset of "
        f"`{args.src.name}` (Ch{args.channel}).\n\n"
        "Run the z-motion benchmark against it:\n\n"
        "```\n"
        f"python tests/benchmarks/benchmark_zcorr.py \\\n"
        f"    --real-zstack {out / args.zstack} \\\n"
        f"    --real-movie {out / args.tseries} --save-results results/\n"
        "```\n"
    )

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"Fixture size (uncompressed): {total / 1e6:.1f} MB")

    if not args.no_tar:
        tar_path = out.with_suffix(".tar.gz")
        print(f"Writing {tar_path} ...")
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(out, arcname=out.name)
        print(f"Archive size: {tar_path.stat().st_size / 1e6:.1f} MB  ->  {tar_path}")
        print("Upload this archive as a GitHub release asset.")


if __name__ == "__main__":
    main()
