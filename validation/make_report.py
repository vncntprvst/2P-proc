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
    import textwrap

    y = 0.86
    for ln in lines:
        indent = 0.10 if ln.startswith("•") else 0.08
        size = 10 if ln.startswith("•") or ln.startswith("  ") else 11
        weight = "bold" if ln.endswith(":") and not ln.startswith("•") else "normal"
        # Wrap manually so we can reserve the right vertical space (fig.text
        # wrap=True doesn't report how many lines it used).
        width = 88 if ln.startswith("•") else 92
        wrapped = textwrap.fill(ln, width=width) if ln else ""
        nlines = wrapped.count("\n") + 1 if ln else 1
        fig.text(indent, y, wrapped, fontsize=size, fontweight=weight, va="top")
        y -= (0.022 * nlines + 0.010) if ln else 0.014
        if y < 0.05:
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
        "2. z-position — synthetic method sweep (accuracy vs drift amplitude)",
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
        "5. z-position — sub-plane interpolation (tested)",
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
        "6. Correction — method comparison (recovery vs drift amplitude)",
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
        "9. Per-ROI correction on real data (CNMF traces)",
        fontsize=13,
        fontweight="bold",
    )
    ax = fig.add_axes([0.05, 0.05, 0.9, 0.87])
    ax.imshow(img)
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)


def section_synthetic_correction(pdf, results):
    traces = results / "roi_zcorr_synthetic.png"
    summ = results / "roi_zcorr_synthetic_summary.png"
    if not traces.exists():
        return
    import matplotlib.image as mpimg

    st = {}
    if (results / "roi_zcorr_synthetic.json").exists():
        st = json.load(open(results / "roi_zcorr_synthetic.json"))
    a = st.get("all_cells", {})
    t = st.get("top_z_impacted", {})

    # Page A: traces
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(
        0.08,
        0.955,
        "8. Correction — recovery on synthetic ground truth",
        fontsize=14,
        fontweight="bold",
    )
    cap = (
        "On real data the benefit is hard to see (no ground truth). Injecting known activity "
        "into the real z-stack lets us quantify recovery. The z-motion is modelled on the real "
        "protocol: fast dynamics (from the real estimated zpos) plus downward motion onsets "
        "clustered around stimulus responses (grey vertical lines) — so the z-artifact partly "
        "overlaps the true responses, the hardest case. For the most z-impacted cells the "
        "correction removes the z-jitter (grey→blue) and recovers the true transients (black)."
    )
    import textwrap

    fig.text(0.08, 0.90, textwrap.fill(cap, 96), fontsize=9.5, va="top")
    ax = fig.add_axes([0.04, 0.06, 0.92, 0.78])
    ax.imshow(mpimg.imread(traces))
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)

    # Page B: summary + stats
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(
        0.08,
        0.955,
        "8. Correction on synthetic ground truth — recovery",
        fontsize=13,
        fontweight="bold",
    )
    if a and t:
        lines = [
            f"All cells:   recovery r {a['r_before_mean']:.2f} → {a['r_after_mean']:.2f}   |   "
            f"residual z-contamination {a['resid_z_before_mean']:.2f} → {a['resid_z_after_mean']:.2f}",
            f"Top z-impacted ({t['n']}): recovery r {t['r_before_mean']:.2f} → {t['r_after_mean']:.2f}   |   "
            f"residual z {t['resid_z_before_mean']:.2f} → {t['resid_z_after_mean']:.2f}",
            "",
            "Benefit: the most z-impacted cells more than double their activity recovery and "
            "shed ~85% of z-contamination. Clean cells are left essentially unchanged.",
            "Limit: recovery plateaus below 1.0 — z-defocus attenuates the true signal, which "
            "additive subtraction cannot restore.",
        ]
        y = 0.90
        for ln in lines:
            fig.text(0.08, y, textwrap.fill(ln, 96) if ln else "", fontsize=9.5, va="top")
            y -= 0.030 * ((len(ln) // 96) + 1) + 0.006 if ln else 0.015
    ax = fig.add_axes([0.08, 0.30, 0.84, 0.42])
    ax.imshow(mpimg.imread(summ))
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)


def section_new_zcorrel(pdf, results):
    png = results / "new_zcorrel_real.png"
    if not png.exists():
        return
    import matplotlib.image as mpimg

    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(
        0.08,
        0.95,
        "4. z-position — optimized compute_zcorrel (legacy → smoothed)",
        fontsize=13,
        fontweight="bold",
    )
    lines = [
        "compute_zcorrel_legacy = full-frame Pearson (kept for comparison).",
        "New compute_zcorrel default = Pearson + temporal median smoothing of zpos.",
        "",
        "Synthetic ground truth (4 seeds): suite2p/phasecorr is most accurate "
        "(RMSE ~0.7 planes) but — see below — fails on mcorr'd data. Pearson+smoothing "
        "edges out legacy (r 0.935 vs 0.920).",
        "",
        "Two synthetic-motivated options were tested and left OFF by default because "
        "they DEGRADE on NoRMCorre-corrected production movies:",
        "• phasecorr (Suite2p): latches onto the deepest low-contrast plane (→ plane 40).",
        "• edge_crop: collapses the Pearson estimate to plane 0.",
        "",
        "The one safe win — temporal smoothing — cuts spurious ≥2-plane jumps on the "
        "real mcorr'd run from 290 (legacy) to 44, tracking the same drift (r=0.85):",
    ]
    y = 0.90
    import textwrap

    for ln in lines:
        wrapped = textwrap.fill(ln, width=92) if ln else ""
        n = wrapped.count("\n") + 1 if ln else 1
        fig.text(0.10 if ln.startswith("•") else 0.08, y, wrapped, fontsize=10, va="top")
        y -= 0.022 * n + 0.010
    ax = fig.add_axes([0.06, 0.10, 0.88, 0.32])
    ax.imshow(mpimg.imread(png))
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)


def _image_page(pdf, title, caption_lines, png, bottom=0.05, cap_top=0.92, x=0.03, w=0.94):
    """Full A4 page: bold title, wrapped caption, then the figure auto-fitted in
    the space that remains below the caption (so text never overlaps the image)."""
    import textwrap
    import matplotlib.image as mpimg

    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.08, 0.965, title, fontsize=14, fontweight="bold")
    y = cap_top
    for ln in caption_lines:
        wrapped = textwrap.fill(ln, 100) if ln else ""
        n = wrapped.count("\n") + 1 if ln else 1
        fig.text(0.08, y, wrapped, fontsize=9.2, va="top")
        y -= 0.019 * n + 0.007 if ln else 0.010
    img_top = max(bottom + 0.15, y - 0.02)  # image occupies caption-bottom → page-bottom
    ax = fig.add_axes([x, bottom, w, img_top - bottom])
    ax.imshow(mpimg.imread(png))
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)


def section_zpos_comparison(pdf, results):
    png = results / "zpos_comparison.png"
    if not png.exists():
        return
    st = {}
    if (results / "zpos_synthetic.json").exists():
        st = json.load(open(results / "zpos_synthetic.json"))
    # Pull the real-concat jump counts so the caption cites the actual numbers.
    concat_line = ""
    cnp = results / "zpos_concat_mcorr.npz"
    if cnp.exists():
        d = np.load(cnp)
        jc = int(np.sum(np.abs(np.diff(d["zpos_caiman"].astype(int))) >= 2))
        js = int(np.sum(np.abs(np.diff(d["zpos_suite2p"].astype(int))) >= 2))
        ag = np.corrcoef(d["zpos_caiman"], d["zpos_suite2p"])[0, 1]
        concat_line = (
            f"On the 3-session real-NoRMCorre concat (C), phase-correlation makes {js} spurious "
            f"≥2-plane jumps vs Pearson's {jc} ({js/max(jc,1):.0f}× more) while tracking the same "
            f"overall drift (agreement r={ag:.2f})."
        )
    cap = [
        "Head-to-head of the two z-position estimators: the shipped Pearson full-frame "
        "correlation (+ temporal median smoothing) vs Suite2p masked phase-correlation.",
        "",
        "A. On SYNTHETIC ground truth Suite2p is more accurate "
        + (
            f"(r {np.mean(st['suite2p']['r']):.3f} vs {np.mean(st['caiman']['r']):.3f}, "
            f"RMSE {np.mean(st['suite2p']['rmse']):.2f} vs {np.mean(st['caiman']['rmse']):.2f} planes)."
            if st
            else "."
        ),
        "B/C. On REAL NoRMCorre output the ranking reverses: phase-correlation is much noisier "
        "(and biased toward deep, low-contrast planes in single sessions), because mcorr edge "
        'artifacts (border_nan="copy") corrupt the masked correlation. Pearson + temporal '
        "smoothing tracks a stable trajectory across sessions (dashed = session boundaries).",
        concat_line,
        "",
        "Since z-position is estimated AFTER motion correction in production, the real-data "
        "behaviour is what matters → the pipeline ships Pearson (no Suite2p dependency).",
    ]
    _image_page(
        pdf,
        "3. z-position: Pearson (shipped) vs Suite2p",
        cap,
        png,
    )


def section_correction_spatial_synth(pdf, results):
    syn = results / "correction_spatial_synthetic.png"
    if not syn.exists():
        return
    st = {}
    if (results / "correction_spatial_synthetic.json").exists():
        st = json.load(open(results / "correction_spatial_synthetic.json"))
    zr = st.get("residual_z_mean", {})
    cap = [
        "The F_anat z-correction can be applied at three spatial granularities. This mirrors "
        "the pipeline's patches_summary_plots style: the top row maps per-pixel residual "
        "z-contamination |corr(ΔF/F, z)| over the FOV after each method (cyan = ROI centers); "
        "the bottom row quantifies recovery and residual z on the extracted ROI traces.",
        "",
        "• per-pixel  — regress every pixel on F_anat (a-priori; over-corrects, mixes noise).",
        "• per-patch  — one scale per spatial patch (coarse).",
        "• per-ROI    — one OLS fit per cell footprint (the shipped method).",
        "",
        (
            (
                f"Residual z-contamination on traces: none {zr.get('none',float('nan')):.2f} → "
                f"per-pixel {zr.get('per-pixel',float('nan')):.2f} → per-patch "
                f"{zr.get('per-patch',float('nan')):.2f} → per-ROI {zr.get('per-ROI',float('nan')):.2f} "
                "(lower is better). Per-ROI removes the most z from the extracted traces while "
                "preserving activity — per-pixel looks lowest pixel-wise but over-corrects, so the "
                "ROI-mean trace keeps more residual z."
            )
            if zr
            else ""
        ),
    ]
    _image_page(pdf, "7. Correction granularity: pixels vs patches vs ROI (synthetic)", cap, syn)


def section_correction_spatial_real(pdf, results):
    real = results / "correction_spatial_real.png"
    if not real.exists():
        return
    st = {}
    if (results / "correction_spatial_real.json").exists():
        st = json.load(open(results / "correction_spatial_real.json"))
    b = st.get("mean_residual_z_before")
    a = st.get("mean_residual_z_after")
    tail = (
        f" Mean ROI residual-z {b:.2f} → {a:.2f} across {st.get('n_rois','?')} ROIs."
        if b is not None
        else ""
    )
    cap = [
        "The shipped per-ROI correction on a real motion-corrected recording (no ground truth). "
        "Left: FOV with extracted ROIs. Middle: per-ROI residual z-contamination |corr(ΔF/F, z)| "
        "before vs after correction (brighter = more z-contaminated). Right: an example ROI trace "
        "(raw vs corrected) with the estimated z overlaid — the correction removes z-locked "
        "fluctuations from the trace." + tail,
    ]
    _image_page(pdf, "10. Per-ROI correction on real data (spatial)", cap, real)


def section_conclusions(pdf):
    _text_page(
        pdf,
        "11. Conclusions & recommendations",
        [
            "Pipeline:",
            "• The z-motion chain is validated end-to-end on real data, both CNMF and "
            "Suite2p backends. 7 latent bugs were fixed in the per-ROI path.",
            "",
            "z-position estimation:",
            "• Synthetic ground truth: phase correlation (Suite2p) is most accurate "
            "(RMSE ~0.7 vs ~1.7 planes for Pearson).",
            "• BUT on real NoRMCorre-corrected movies this does not transfer: phasecorr is much "
            "noisier — 94 vs 18 spurious ≥2-plane jumps on the 3-session concat (5×), and a "
            "deep-plane bias in single sessions — and edge-cropping collapses Pearson to plane 0. "
            "Since z-pos runs after mcorr, phasecorr is not usable there.",
            "• The robust improvement is Pearson + temporal median smoothing of zpos: same "
            "drift as legacy but 44 vs 290 spurious ≥2-plane jumps on the real single run.",
            "• Recommendation: keep Pearson (now the default in compute_zcorrel) with "
            "temporal smoothing; do NOT adopt phasecorr/edge-crop for production despite "
            "their synthetic accuracy. Revisit phasecorr only for raw/lightly-registered data.",
            "",
            "F_anat & correction:",
            "• Per-ROI fit-and-subtract removes the most z-contamination at every drift "
            "amplitude; per-pixel/per-patch trail. Recovery is capped by defocus attenuation.",
            "• Sub-plane interpolation of the z-peak gives negligible gain (global or F_anat) "
            "— not worth adding.",
        ],
        subtitle="What works, and what to do next",
    )


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

        # 1. Pipeline validation
        section_pipeline(pdf)
        # 2–5. z-position estimation
        section_stage1(pdf, args.results)  # 2. synthetic amplitude sweep
        section_zpos_comparison(pdf, args.results)  # 3. Pearson vs Suite2p (synthetic + real)
        section_new_zcorrel(pdf, args.results)  # 4. optimized compute_zcorrel
        section_stage1b(pdf, args.results)  # 5. sub-plane interpolation
        # 6–10. correction
        section_stage3(pdf, args.results)  # 6. method comparison sweep
        section_correction_spatial_synth(pdf, args.results)  # 7. granularity (synthetic, spatial)
        section_synthetic_correction(pdf, args.results)  # 8. recovery on synthetic ground truth
        section_roi_figure(pdf, args.results)  # 9. per-ROI on real data (traces)
        section_correction_spatial_real(pdf, args.results)  # 10. per-ROI on real data (spatial)
        # 11. Conclusions
        section_conclusions(pdf)

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
