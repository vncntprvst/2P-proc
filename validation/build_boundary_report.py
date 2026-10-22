"""Build the run-boundary report (single HTML page, figures embedded).

Usage: python validation/build_boundary_report.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_realdata_report import CSS, img  # noqa: E402
from make_boundary_figures import DATASETS, RES  # noqa: E402

FIG = HERE / "report" / "boundary"


def load(stem):
    f = RES / f"{stem}.json"
    return json.loads(f.read_text()) if f.exists() else None


def pct(v, d=2):
    return f"{100 * v:.{d}f}"


def datasets_table():
    rows = []
    for lab, _, stem, notes in DATASETS:
        R = load(stem)
        if R is None:
            continue
        st, zp = R["F_step"], R["zpos"]
        for i, note in enumerate(notes):
            rows.append(
                f"<tr><th scope='row'>{lab}<span class='sub'>boundary {i + 1}: {note}</span></th>"
                f"<td class='num'>{' + '.join(map(str, R['runs']))}</td><td class='num'>{R['n_rois']}</td>"
                f"<td class='num'>{zp['pearson']['boundary_jump'][i]:+.0f} / {zp['suite2p']['boundary_jump'][i]:+.0f}</td>"
                f"<td class='num'>{pct(st['abs_median_per_boundary'][i], 1)}</td>"
                f"<td class='num'>{pct(st['F_anat_pearson_abs_median'][i], 1)}</td>"
                f"<td class='num'>{st['corr_F_vs_F_anat_pearson'][i]:.2f}</td>"
                f"<td class='num'>{pct(st['made_up_p95_of_boundary_medians'], 1)}</td></tr>")
    head = ("<th></th><th>frames per run</th><th>ROIs</th><th>z jump, planes (Pearson / Suite2p)</th>"
            "<th>|ΔF| step, %</th><th>predicted from depth, %</th><th>r across ROIs</th>"
            "<th>made-up boundaries, 95th pct, %</th>")
    return f"<div class='tablewrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def fit_table():
    rows = []
    for lab, _, stem, _ in DATASETS:
        for mode, suffix in (("argmax", ""), ("soft", "_soft200")):
            R = load(stem + suffix)
            if R is None:
                continue
            f = R["fit"]
            ex = next(v for k, v in f.items() if k.startswith("per_run_excl"))
            vals = [f["no_correction_r2"]["median"], f["one_baseline"]["heldout_resid_r2"]["median"],
                    f["per_run"]["heldout_resid_r2"]["median"], ex["heldout_resid_r2"]["median"]]
            ratio = vals[1] / vals[2]
            cells = "".join(f"<td class='num'>{pct(v)}</td>" for v in vals)
            rows.append(f"<tr><th scope='row'>{lab}<span class='sub'>{mode} depth</span></th>{cells}"
                        f"<td class='num good'>{ratio:.1f}×</td></tr>")
    head = ("<th></th><th>no correction</th><th>one baseline (before)</th><th>per-run baselines (now)</th>"
            "<th>per run, 200 frames after each boundary left out of the fit</th><th>one / per run</th>")
    return f"<div class='tablewrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def zpos_table():
    est = [("pearson_raw", "Pearson, no median filter"), ("suite2p", "Suite2p-style"),
           ("suite2p_med5", "Suite2p-style + median")]
    rows = []
    for lab, _, stem, _ in DATASETS:
        for mode, suffix in (("argmax", ""), ("soft", "_soft200")):
            R = load(stem + suffix)
            if R is None:
                continue
            z = R["zpos_fit"]
            cells = f"<td class='num'>{pct(z['pearson']['heldout_explained']['median_top25'], 1)}</td>"
            for k, _ in est:
                g, p = z[k]["vs_pearson_median_gain_top25"], z[k]["vs_pearson_wilcoxon_p"]
                cls = "" if p >= 0.01 else (" good" if g > 0 else " bad")
                cells += f"<td class='num{cls}'>{100 * g:+.2f}<span class='sub'>p {p:.1g}</span></td>"
            rows.append(f"<tr><th scope='row'>{lab}<span class='sub'>{mode} depth</span></th>{cells}</tr>")
    head = "<th></th><th>pipeline (Pearson + median), %</th>" + "".join(f"<th>{n}, gain</th>" for _, n in est)
    return f"<div class='tablewrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def ratio_range():
    r = []
    for _, _, stem, _ in DATASETS:
        for suffix in ("", "_soft200"):
            R = load(stem + suffix)
            if R:
                r.append(R["fit"]["one_baseline"]["heldout_resid_r2"]["median"]
                         / R["fit"]["per_run"]["heldout_resid_r2"]["median"])
    return f"{min(r):.0f}–{max(r):.0f}"


def build():
    n_sets = sum(load(s) is not None for _, _, s, _ in DATASETS)
    rr = ratio_range()
    body = f"""
<header style="display:flex;flex-direction:column;gap:10px">
  <span class="eyebrow">2P-proc · benchmark branch · validation report</span>
  <h1>Run boundaries in concatenated recordings</h1>
  <p class="lede">Runs from one session are concatenated before extraction so that every run gets the same ROIs.
  Does the jump between runs hurt the z-correction, and does the choice of z-position estimator matter there?
  {n_sets} concatenated recordings were checked, chosen for what changes between runs: nothing, laser setting,
  an unexplained drop in brightness, and a 9 µm stage refocus.</p>
  <p class="meta">Written for the Wang lab 2P group. Pipeline: Suite2p extraction, non-rigid F_anat (60 px
  patches), per-ROI fit in ΔF/F. Data: Scnn1aAi14_D1M2 08/29 and 08/21/2026, Scnn1aAi14_B2M0 04/22/2024,
  C57_O1M2 10/19/2023, Scnn1aAi14_2P11 07/11/2024; 16×, 765 × 765 px, 20 Hz. Code:
  <code>validation/boundary_benchmark.py</code>.</p>
</header>

<h2>Summary</h2>
<div class="keys">
  <div class="key"><b>Fit each run with its own baseline</b><span>With one ΔF/F baseline over the concatenated
  trace, a fluorescence step between runs drives the per-ROI slope. Per-run baselines leave {rr}× less
  z-dependence inside the runs, in every recording and with both depth rules. This is now the pipeline
  default.</span></div>
  <div class="key"><b>Most steps between runs are not depth</b><span>Fluorescence changed by about 25% at two
  boundaries where depth predicts 1–6% (laser setting +8%; a 21% drop in raw brightness of unknown cause). Only
  the 9 µm refocus produced a step that depth explains (r = 0.81).</span></div>
  <div class="key"><b>The Suite2p-style failure was a bug</b><span>Our port handed the movie to parallel workers
  as a strided memmap view; for C-order CaImAn memmaps the workers read wrong pixels and the estimate piled up at
  the first and last planes. Fixed. Since then it tracks the Pearson estimate, including across every
  boundary.</span></div>
  <div class="key"><b>Keep the Pearson estimator</b><span>With soft depth, which the auto mode selects, the
  estimators give the same correction (differences ≤ 0.1 points of %). With argmax depth the differences are small
  and change sign between recordings. Pearson is also 1.4–1.7× faster.</span></div>
</div>

<h2>1 · Recordings and what happens at each boundary</h2>
<p>Pairs of runs at the same position and zoom were picked from the Bruker headers of all sessions with two or
more runs and a z-stack. The z-stack covers ±20 µm around the imaging plane in each case (checked from its
per-frame positions).</p>
<figure><div class="plate">{img('fig_boundary_zpos.png', 'z-position across concatenated runs', FIG)}</div>
<figcaption>Both estimators follow the 10-plane jump after the 9 µm refocus (2P11) and the 3-plane jump on
B2M0. Neither shows a jump at a boundary that the other does not.</figcaption></figure>
<figure><div class="plate">{img('fig_boundary_steps.png', 'Fluorescence step at each boundary', FIG)}</div>
<figcaption>Median over ROIs of the change in F across each boundary (400 frames each side), against the change
F_anat predicts from depth and against the same statistic at made-up boundaries inside runs. r: correlation of
the measured and predicted steps across ROIs.</figcaption></figure>
{datasets_table()}
<p>On B2M0 the 21% drop is already in the raw channel-2 TIFFs (and channel 1 drops 33%, which matches its PMT
going from 750 to 600 V). The channel-2 PMT and the laser setting (+3%) do not explain it.</p>

<h2>2 · The per-ROI fit across boundaries</h2>
<p>Each variant fits the slope of ΔF/F on ΔF/F_anat on alternate 400-frame blocks and is scored on the others:
the fraction of within-run ΔF/F variance that F_anat still explains after correction (0 is best). ROIs: Suite2p
iscell.</p>
<figure><div class="plate">{img('fig_boundary_fit.png', 'Held-out z-dependence left by the fit', FIG)}</div></figure>
{fit_table()}
<p>Leaving out the first 200 frames (10 s) of each run from the fit does not help, so
<code>boundary_exclude_frames</code> stays at 0. When the step is real depth (2P11), per-run baselines are still
better: a 10-plane step sits outside the range where F follows depth linearly, and with one baseline it
dominates the slope.</p>
<p class="callout">Pipeline change: <code>run_roi_zcorr</code> reads the frames of each run from
<code>stim_sequence.json</code> (now also written per run) and computes ΔF/F baselines per run; the slope is shared
by all runs. Option <code>roi_correction.per_run</code> (default true). The auto depth mode skips z-events whose
window spans a boundary. The MATLAB analysis computes ΔF/F with per-trial baselines, which already removes
steps between runs.</p>

<h2>3 · z-position estimators</h2>
<p>The pipeline estimates z-position by Pearson correlation of each smoothed frame with the shifted z-stack,
then applies a 5-frame median filter. The Suite2p-style estimator (<code>compute_zcorrel_suite2p</code>, Suite2p's
masked phase correlation) had been set aside because it "latched onto the deepest plane" on motion-corrected
movies.</p>
<figure><div class="plate">{img('fig_phasecorr_bug.png', 'Phase-correlation profiles before and after the fix', FIG)}</div>
<figcaption>C57_O1M2 10/02, an older export saved as a C-order memmap. Before the fix the correlation is flat
over planes and the estimate falls at random, piling up at planes 0 and 40. Called on the same frames in one
process, the correlation peaks at plane 11–12, as the Pearson estimate does.</figcaption></figure>
<p>The cause was in our port, not in Suite2p: it passed the whole movie to joblib workers, and a C-order memmap
reshaped to frames is a strided view that the workers read with the wrong pixel order. Each task now receives
one contiguous frame. Results on F-order memmaps (all current pipeline exports) are unchanged, verified
identical on B2M0. The pipeline's own Pearson path was never affected.</p>
<figure><div class="plate">{img('fig_zpos_methods.png', 'z-position estimators against the pipeline', FIG)}</div>
<figcaption>Held-out fraction of within-run ΔF/F variance explained by F_anat built from each z-position estimate,
as a gain over the pipeline estimate (25% most z-loaded ROIs, paired over ROIs).</figcaption></figure>
{zpos_table()}
<p>With argmax depth, dropping the median filter or using the Suite2p-style estimate helps on two recordings and
hurts on one; with soft depth none of the differences exceeds 0.1 points of %. Soft depth searches ±8 planes
around the global z-position for each patch, so the global estimate only has to be close. No estimator fails at a
run boundary.</p>

<h2>Open items</h2>
<ul>
  <li>Detection: whether the step at a boundary creates or merges ROIs in Suite2p was not tested.</li>
  <li>Suite2p deconvolution runs on the concatenated trace. On D1M2 08/29 the event rate in the 5 s after the
  boundary was 1.22× the run median (1.12× after the start of run 1); not studied further.</li>
  <li>On the cluster, <code>~/.cache</code> points to scratch, which the 2p_proc container does not mount, so
  CaImAn's import of pynwb fails. Passing <code>APPTAINERENV_XDG_CACHE_HOME=/tmp/xdg_cache</code> works around it;
  the template script could set it.</li>
</ul>

<h2>Reproduce</h2>
<p class="meta">pixi run python validation/zpos_suite2p.py &lt;movie.mmap&gt; &lt;zstack_shifted.tif&gt;
&lt;export&gt;/zpos_suite2p<br>pixi run python validation/boundary_benchmark.py &lt;export&gt; --zpos
suite2p=&lt;export&gt;/zpos_suite2p/z_correlation_suite2p.npz [--depth-mode soft200] --out
validation/results/boundary/&lt;name&gt;.json<br>python validation/make_boundary_figures.py; python
validation/build_boundary_report.py<br>Configs: validation/configs/ (local) and validation/configs/engaging/
(cluster); cluster job for the z-position: validation/cluster/zpos_suite2p.sh</p>
"""
    return f"""<title>Run boundaries in concatenated recordings</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>{CSS}</style>
<main>{body}</main>
"""


def main():
    out = FIG / "boundary_report.html"
    out.write_text(build())
    print(out, f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
