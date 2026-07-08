"""Compose the z-motion correction methodology PDF report.

Reads result files from a results directory (JSON tables + a couple of .npz
trajectories + figures) and composes a multi-section PDF with matplotlib. Each
benchmark/validation is its own section. Sections whose inputs are missing are
skipped, so the report can be regenerated as data becomes available.

Expected inputs in --results DIR (all optional):
    stage1_zpos.json            list of stage-1 z-pos method cases
    stage1b_subplane.json       {"global": [...], "fanat": [...]}
    stage3_sweep.json           list of {z_amp, none/per_roi/per_pixel/per_patch}
    zpos_synthetic.json         {"caiman": {r:[...],rmse:[...]}, "suite2p": {...}}
    zpos_single.npz             (zpos_caiman, zpos_suite2p, [fs])
    zpos_concat.npz             (zpos_caiman, zpos_suite2p, boundaries)
    roi_zcorr_traces.png        real-data raw-vs-corrected figure

Usage: python validation/make_report.py --results DIR --out report.pdf
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np


def _text_page(pdf, title, lines, subtitle=None):
    fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
    fig.text(0.08, 0.94, title, fontsize=18, fontweight="bold")
    if subtitle:
        fig.text(0.08, 0.905, subtitle, fontsize=10, style="italic", color="0.3")
    y = 0.86
    for ln in lines:
        indent = 0.10 if ln.startswith("•") else 0.08
        size = 10 if ln.startswith("•") or ln.startswith("  ") else 11
        weight = "bold" if ln.endswith(":") and not ln.startswith("•") else "normal"
        fig.text(indent, y, ln, fontsize=size, fontweight=weight, wrap=True)
        y -= 0.030 if ln else 0.018
        if y < 0.06:
            break
    pdf.savefig(fig)
    plt.close(fig)


def _table_page(pdf, title, col_labels, rows, note=None, highlight_col=None):
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.08, 0.94, title, fontsize=16, fontweight="bold")
    ax = fig.add_axes([0.08, 0.55, 0.84, 0.32])
    ax.axis("off")
    tbl = ax.table(cellText=rows, colLabels=col_labels, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.6)
    for j in range(len(col_labels)):
        tbl[0, j].set_facecolor("#40466e")
        tbl[0, j].set_text_props(color="w", fontweight="bold")
    if note:
        fig.text(0.08, 0.50, note, fontsize=9.5, wrap=True, color="0.2")
    pdf.savefig(fig)
    plt.close(fig)


def section_pipeline(pdf):
    _text_page(
        pdf,
        "1. End-to-end pipeline validation",
        [
            "The z-motion correction chain was validated on real data " "(C57_O1M2/10022023):",
            "mcorr → z-motion (F_anat) → ROI extraction → per-ROI fit-and-subtract.",
            "",
            "Coverage:",
            "• Subset (TSeries-001, 200 frames) and full session (1600 frames).",
            "• Both extraction backends: CNMF and Suite2p (0.14.0).",
            "• Full session: real z-drift over planes 9–16 (~7 µm, σ≈1 µm); "
            "593 ROIs → F_roi_zcorrected.",
            "",
            "7 bugs fixed in the under-tested per-ROI path (normally done in MATLAB):",
            "• create_components_movie excerpt overflow on short recordings.",
            "• CNMF extraction now writes cnmf_result.hdf5 for run_roi_zcorr.",
            "• load_CNMF(n_processes=1); raw F = C+YrA; dims from cnm.dims (caiman 1.12).",
            "• compute_zcorrel_suite2p: contiguous flip + worker-scope rigid (suite2p 0.14).",
            "",
            "Environment: pixi (CaImAn 1.12.2 + Suite2p 0.14.0 pinned to production). "
            "The pipeline requires an activated env — bare `python` may be Python 2.",
        ],
        subtitle="Validation of the current method on real anatomy",
    )


def section_stage1(pdf, results):
    f = results / "stage1_zpos.json"
    if not f.exists():
        return
    data = json.load(open(f))
    labels = [f"{d['motion_type']}\namp{d['amplitude_planes']:.0f}" for d in data]
    x = np.arange(len(data))
    fig, axes = plt.subplots(2, 1, figsize=(8.27, 9.5))
    for ax, key, ylab in [
        (axes[0], "r", "z-pos vs truth (Pearson r)"),
        (axes[1], "rmse_um", "RMSE (µm)"),
    ]:
        cai = [d["caiman"][key] for d in data]
        s2p = [d["suite2p"][key] for d in data]
        cai = [np.nan if v is None else v for v in cai]
        s2p = [np.nan if v is None else v for v in s2p]
        ax.bar(x - 0.2, cai, 0.4, label="compute_zcorrel", color="C0")
        ax.bar(x + 0.2, s2p, 0.4, label="suite2p port", color="C1")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylabel(ylab)
        ax.legend(fontsize=8)
    times = [(d["caiman"]["time_s"], d["suite2p"]["time_s"]) for d in data]
    tnote = "  ".join(
        f"{labels[i].replace(chr(10),' ')}: {t[0]:.1f}s vs {t[1]:.1f}s" for i, t in enumerate(times)
    )
    fig.suptitle(
        "2. Stage 1 — z-position method comparison " "(compute_zcorrel vs Suite2p port)",
        fontsize=13,
        fontweight="bold",
    )
    fig.text(
        0.08,
        0.02,
        "Suite2p is more accurate (higher r, lower RMSE) but slower — " f"time/case: {tnote}",
        fontsize=8,
        color="0.2",
        wrap=True,
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.96])
    pdf.savefig(fig)
    plt.close(fig)


def section_stage1b(pdf, results):
    f = results / "stage1b_subplane.json"
    if not f.exists():
        return
    d = json.load(open(f))
    rows = []
    for g in d.get("global", []):
        rows.append(
            [
                f"global z, amp {g['amp']:.0f}",
                "RMSE planes",
                f"{g['integer']:.3f}",
                f"{g['subplane']:.3f}",
            ]
        )
    for g in d.get("fanat", []):
        rows.append(
            [
                f"F_anat corr, amp {g['amp']:.0f}",
                "recovery r",
                f"{g['integer']:.3f}",
                f"{g['subplane']:.3f}",
            ]
        )
    _table_page(
        pdf,
        "3. Stage 1b — sub-plane interpolation (tested)",
        ["case", "metric", "integer argmax", "sub-plane"],
        rows,
        note="Parabolic interpolation of the correlation peak was expected to beat "
        "integer argmax for both the global z-position and the per-patch depth used to "
        "build F_anat. Tested: negligible improvement in both. The error is dominated by "
        "discrete multi-plane misassignments and defocus signal attenuation, not ±0.5-plane "
        "quantization. Conclusion: sub-plane is not worth adding; improve plane-selection "
        "robustness or use the more accurate Suite2p estimator instead.",
    )


def section_stage3(pdf, results):
    f = results / "stage3_sweep.json"
    if not f.exists():
        return
    data = json.load(open(f))
    amps = [d["z_amp"] for d in data]
    methods = ["none", "per_roi", "per_pixel", "per_patch"]
    colors = {"none": "0.5", "per_roi": "C0", "per_pixel": "C1", "per_patch": "C2"}
    fig, axes = plt.subplots(1, 2, figsize=(8.27, 5.2))
    for m in methods:
        axes[0].plot(amps, [d[m]["recovery_r"] for d in data], "-o", label=m, color=colors[m])
        axes[1].plot(amps, [d[m]["residual_z_r"] for d in data], "-o", label=m, color=colors[m])
    axes[0].set_title("Activity recovery (higher better)")
    axes[0].set_xlabel("z-drift (planes)")
    axes[0].set_ylabel("recovery r")
    axes[1].set_title("Residual z-contamination (lower better)")
    axes[1].set_xlabel("z-drift (planes)")
    axes[1].set_ylabel("residual z-r")
    axes[0].legend(fontsize=8)
    fig.suptitle(
        "4. Stage 3 — correction method comparison " "(synthetic activity ground truth)",
        fontsize=12,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.01,
        "per-ROI removes the most z-contamination at every amplitude; "
        "recovery is capped by defocus attenuation.",
        ha="center",
        fontsize=8,
        color="0.2",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.93])
    pdf.savefig(fig)
    plt.close(fig)


def section_zpos_deepdive(pdf, results):
    syn = results / "zpos_synthetic.json"
    single = results / "zpos_single.npz"
    concat = results / "zpos_concat.npz"
    if not any(p.exists() for p in (syn, single, concat)):
        return

    if syn.exists():
        d = json.load(open(syn))
        fig, axes = plt.subplots(1, 2, figsize=(8.27, 4.6))
        for ax, key, ylab in [(axes[0], "r", "Pearson r"), (axes[1], "rmse", "RMSE (planes)")]:
            for i, meth in enumerate(["caiman", "suite2p"]):
                vals = d[meth][key]
                ax.bar(
                    i, np.mean(vals), 0.6, yerr=np.std(vals), capsize=4, color=f"C{i}", label=meth
                )
            ax.set_xticks([0, 1])
            ax.set_xticklabels(["compute_zcorrel", "suite2p"], fontsize=8)
            ax.set_ylabel(ylab)
        n = len(d["caiman"]["r"])
        fig.suptitle(
            f"5a. z-pos on synthetic data — mean±std over {n} seeds", fontsize=12, fontweight="bold"
        )
        fig.tight_layout(rect=[0, 0, 1, 0.92])
        pdf.savefig(fig)
        plt.close(fig)

    if single.exists():
        z = np.load(single)
        fig, ax = plt.subplots(figsize=(8.27, 4.0))
        ax.plot(z["zpos_caiman"], color="C0", lw=0.8, label="compute_zcorrel")
        ax.plot(z["zpos_suite2p"], color="C1", lw=0.8, label="suite2p")
        ax.set_xlabel("frame")
        ax.set_ylabel("estimated z-plane")
        ax.legend(fontsize=8)
        jc = int(np.sum(np.abs(np.diff(z["zpos_caiman"])) >= 2))
        js = int(np.sum(np.abs(np.diff(z["zpos_suite2p"])) >= 2))
        ag = float(np.corrcoef(z["zpos_caiman"], z["zpos_suite2p"])[0, 1])
        fig.suptitle(
            "5b. z-pos on a single real run (TSeries-001, no ground truth)",
            fontsize=12,
            fontweight="bold",
        )
        fig.text(
            0.08,
            0.01,
            f"agreement r={ag:.3f}; ≥2-plane jumps: "
            f"compute_zcorrel={jc}, suite2p={js} (fewer = smoother)",
            fontsize=8.5,
            color="0.2",
        )
        fig.tight_layout(rect=[0, 0.04, 1, 0.93])
        pdf.savefig(fig)
        plt.close(fig)

    if concat.exists():
        z = np.load(concat)
        bnds = z["boundaries"]
        fig, ax = plt.subplots(figsize=(8.27, 4.0))
        ax.plot(z["zpos_caiman"], color="C0", lw=0.7, label="compute_zcorrel")
        ax.plot(z["zpos_suite2p"], color="C1", lw=0.7, label="suite2p")
        for b in bnds:
            ax.axvline(b, color="0.7", ls="--", lw=0.8)
        ax.set_xlabel("frame (dashed = session boundaries)")
        ax.set_ylabel("estimated z-plane")
        ax.legend(fontsize=8)

        def boundary_jump(zp):
            return float(
                np.mean([abs(int(zp[b]) - int(zp[b - 1])) for b in bnds if 0 < b < len(zp)])
            )

        fig.suptitle("5c. z-pos on concatenated 4-session data", fontsize=12, fontweight="bold")
        fig.text(
            0.08,
            0.01,
            "mean |z jump| at boundaries: "
            f"compute_zcorrel={boundary_jump(z['zpos_caiman']):.2f}, "
            f"suite2p={boundary_jump(z['zpos_suite2p']):.2f} planes",
            fontsize=8.5,
            color="0.2",
        )
        fig.tight_layout(rect=[0, 0.04, 1, 0.93])
        pdf.savefig(fig)
        plt.close(fig)


def section_roi_figure(pdf, results):
    png = results / "roi_zcorr_traces.png"
    if not png.exists():
        return
    import matplotlib.image as mpimg

    img = mpimg.imread(png)
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(
        0.08,
        0.95,
        "6. Real-data per-ROI correction (full TSeries-001)",
        fontsize=13,
        fontweight="bold",
    )
    ax = fig.add_axes([0.05, 0.05, 0.9, 0.87])
    ax.imshow(img)
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    out = args.out or (args.results / "zmotion_report.pdf")

    with PdfPages(out) as pdf:
        # Title page
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.5, 0.62, "Z-motion correction", ha="center", fontsize=26, fontweight="bold")
        fig.text(0.5, 0.565, "validation & benchmarking", ha="center", fontsize=18)
        fig.text(
            0.5,
            0.50,
            "optimouse 2-photon pipeline — C57_O1M2/10022023",
            ha="center",
            fontsize=12,
            color="0.3",
        )
        fig.text(
            0.5,
            0.46,
            "CaImAn 1.12.2 · Suite2p 0.14.0 · real 41-plane z-stack",
            ha="center",
            fontsize=10,
            color="0.4",
        )
        pdf.savefig(fig)
        plt.close(fig)

        section_pipeline(pdf)
        section_stage1(pdf, args.results)
        section_stage1b(pdf, args.results)
        section_stage3(pdf, args.results)
        section_zpos_deepdive(pdf, args.results)
        section_roi_figure(pdf, args.results)

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
