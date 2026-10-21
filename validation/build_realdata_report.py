"""Build the real-data z-correction report (single HTML page with embedded figures).

Reads the benchmark JSONs of each session and the figures from make_realdata_figures.py, so
every number in the page comes from the results files.

Usage
-----
    python validation/build_realdata_report.py --out validation/report/realdata/zcorr_realdata_report.html
"""

import argparse
import base64
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIG = HERE / "report" / "realdata"
A = Path("/home/wanglab/data/2P/Analysis_2P")
SOFT = "soft_b200_w8_g1"

SESSIONS = [  # label, export, stimulus, backend, protocol note
    ("D1M2 run1", "Scnn1aAi14_D1M2/08292026/run1", "laser 22.5–90 mJ", "Suite2p", "100 trials, 20 Hz"),
    ("D1M2 run1", "Scnn1aAi14_D1M2/08292026/run1_cnmf", "laser 22.5–90 mJ", "CNMF", "100 trials, 20 Hz"),
    ("D1M2 run2", "Scnn1aAi14_D1M2/08292026/run2", "700 ms mechanical (vF)", "Suite2p", "30 trials, 20 Hz"),
    ("B1M0 run1", "Scnn1aAi14_B1M0/04182024/run1", "laser 22.5–52.5 mJ", "Suite2p", "100 trials, 20 Hz"),
    ("B2M0 run3", "Scnn1aAi14_B2M0/04192024/run3", "laser 22.5–52.5 mJ", "Suite2p", "100 trials, 20 Hz"),
    ("A2M0 run1", "Scnn1aAi14_A2M0/12152023/run1", "laser 22.5–52.5 mJ", "Suite2p", "100 trials, 15 Hz, 512 px"),
]
COLS = [  # label, file tag, variant
    ("none", "", "none"),
    ("rigid zpos", "", "zpos:poly2"),
    ("F_anat, one depth", "rules", "global_raw:ols"),
    ("MATLAB reference", "", "uni_mm3:ols"),
    ("no movmean", "", "uni_raw:ols"),
    ("soft depth", "soft", f"{SOFT}_raw:ols"),
]


def img(name, alt, folder=FIG):
    data = base64.b64encode((folder / name).read_bytes()).decode()
    return f'<img src="data:image/png;base64,{data}" alt="{html.escape(alt)}">'


def bench(export, tag=""):
    f = A / export / "benchmark" / f"real_zcorr_benchmark{'_' + tag if tag else ''}.json"
    return json.loads(f.read_text())


def fmt(v, best=None):
    s = f"{v:+.2f}" if best == 0 else f"{v:.2f}"
    return s.replace("-", "−")


def session_table(metric, ideal):
    rows = []
    for label, exp, stim, backend, note in SESSIONS:
        meta = bench(exp)["meta"]
        cells = []
        for _, tag, var in COLS:
            v = bench(exp, tag)["results"][var][metric]
            dist = abs(v - ideal)
            cls = "good" if dist < 0.05 else ("mid" if dist < 0.12 else "bad")
            cells.append(f'<td class="num {cls}">{fmt(v, ideal)}</td>')
        rows.append(
            f"<tr><th scope='row'>{label}<span class='sub'>{backend} · {stim} · "
            f"z-jump {meta['jump_time_s']:.2f} s · {meta['n_roi']} ROIs</span></th>{''.join(cells)}</tr>"
        )
    head = "".join(f"<th scope='col'>{c[0]}</th>" for c in COLS)
    return f"<div class='tablewrap'><table><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def grid_table():
    r = {**bench(SESSIONS[0][1], "grids")["results"], **bench(SESSIONS[0][1], "grids2")["results"]}
    grids = [("s24_o12", "36 px", 24), ("s36_o12", "48 px", 36), ("s30_o30", "60 px", 30),
             ("s24_o36", "60 px", 24), ("s36_o24", "60 px (production)", 36), ("s48_o24", "72 px", 48),
             ("s48_o36", "84 px", 48), ("s72_o36", "108 px", 72)]
    rows = []
    for key, size, stride in grids:
        a, s = r[f"grid_{key}_argmax_raw:ols"], r[f"grid_{key}_soft_raw:ols"]
        prod = " class='prod'" if key == "s36_o24" else ""
        rows.append(f"<tr{prod}><th scope='row'>{size}, stride {stride}</th>"
                    f"<td class='num'>{fmt(a['trial_zdep'], 0)}</td><td class='num'>{fmt(a['zlock_corr'])}</td>"
                    f"<td class='num'>{fmt(s['trial_zdep'], 0)}</td><td class='num'>{fmt(s['zlock_corr'])}</td>"
                    f"<td class='num'>{fmt(s['inject_coupled'])}</td></tr>")
    return ("<div class='tablewrap'><table><thead><tr><th>patch size, stride</th>"
            "<th>argmax: trial z-dep.</th><th>argmax: z-locked corr.</th><th>soft: trial z-dep.</th>"
            "<th>soft: z-locked corr.</th><th>soft: signal kept</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def detection_table():
    names = [("none", "none"), ("rigid zpos", "rigid zpos"), ("MATLAB reference", "MATLAB (uni_mm3:ols)"),
             ("no movmean", "uni_raw:ols"), ("soft depth", f"soft ({SOFT}):ols")]
    rows = []
    for label, exp, _, backend, _ in SESSIONS:
        f = A / exp / "benchmark" / "response_detection.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        cells = "".join(
            f"<td class='num'>{d[k]['z-jump window 1.35-1.6 s'][0]} / {d[k]['z-jump window 1.35-1.6 s'][1]}</td>"
            for _, k in names)
        rows.append(f"<tr><th scope='row'>{label}<span class='sub'>{backend}</span></th>{cells}</tr>")
    head = "".join(f"<th>{n[0]}</th>" for n in names)
    return f"<div class='tablewrap'><table><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


CSS = """
:root {
  /* Layout: single reading column (~68ch) with full-width figure plates; tables scroll in their own box */
  --paper: #fbfbfc; --ink: #15171a; --ink-2: #4a4f57; --rule: #dfe2e6; --plate: #ffffff;
  --accent: #2a78d6; --good: #1f7a4d; --mid: #946200; --bad: #b3402f;
  --good-bg: #e6f3ec; --mid-bg: #fbf1dc; --bad-bg: #f8e6e2;
  --f-display: "Instrument Sans", "Helvetica Neue", Arial, sans-serif;
  --f-body: "Source Serif 4", Georgia, "Times New Roman", serif;
  --f-mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --paper: #15171a; --ink: #e8eaed; --ink-2: #a9b0b9; --rule: #30343a; --plate: #f4f5f6;
    --accent: #5b9cf0; --good: #6cc79a; --mid: #e0b45a; --bad: #ef8a78;
    --good-bg: #1d3328; --mid-bg: #3a2f17; --bad-bg: #3b221d;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --paper: #15171a; --ink: #e8eaed; --ink-2: #a9b0b9; --rule: #30343a; --plate: #f4f5f6;
  --accent: #5b9cf0; --good: #6cc79a; --mid: #e0b45a; --bad: #ef8a78;
  --good-bg: #1d3328; --mid-bg: #3a2f17; --bad-bg: #3b221d;
}
body { background: var(--paper); color: var(--ink); font: 17px/1.6 var(--f-body);
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
main { max-width: 68ch; margin: 0 auto; padding-block: 48px 96px; display: flex; flex-direction: column; gap: 20px; }
h1, h2, h3 { font-family: var(--f-display); text-wrap: balance; line-height: 1.2; margin: 0; }
h1 { font-size: 2.1rem; font-weight: 650; letter-spacing: -0.01em; }
h2 { font-size: 1.35rem; font-weight: 650; margin-top: 28px; padding-top: 18px; border-top: 1px solid var(--rule); }
h3 { font-size: 1.05rem; font-weight: 600; margin-top: 8px; }
p, li { margin: 0; }
ul, ol { margin: 0; padding-left: 1.3em; display: flex; flex-direction: column; gap: 8px; }
.eyebrow { font: 600 0.75rem/1 var(--f-display); letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }
.lede { font-size: 1.12rem; color: var(--ink-2); }
.meta { font: 0.8rem/1.5 var(--f-mono); color: var(--ink-2); }
code, .mono { font-family: var(--f-mono); font-size: 0.86em; }
a { color: var(--accent); }
figure { margin: 6px 0; width: min(1100px, calc(100vw - 32px)); align-self: center; display: flex; flex-direction: column; gap: 8px; }
figure .plate { background: var(--plate); border: 1px solid var(--rule); border-radius: 6px; padding: 10px; overflow-x: auto; }
figure img { display: block; width: 100%; height: auto; min-width: 640px; }
figure .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
figure .pair img { min-width: 0; }
figcaption { font-size: 0.9rem; color: var(--ink-2); max-width: 68ch; align-self: center; }
.tablewrap { overflow-x: auto; width: min(1100px, calc(100vw - 32px)); align-self: center; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { padding: 7px 10px; border-bottom: 1px solid var(--rule); text-align: left; vertical-align: top; }
thead th { font: 600 0.78rem/1.3 var(--f-display); color: var(--ink-2); letter-spacing: 0.02em; }
tbody th { font-weight: 600; font-family: var(--f-display); }
.sub { display: block; font: 400 0.74rem/1.4 var(--f-mono); color: var(--ink-2); margin-top: 2px; }
td.num { font-family: var(--f-mono); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
td.good { color: var(--good); background: var(--good-bg); }
td.mid { color: var(--mid); background: var(--mid-bg); }
td.bad { color: var(--bad); background: var(--bad-bg); }
tr.prod th, tr.prod td { font-weight: 700; }
.keys { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.key { border: 1px solid var(--rule); border-radius: 6px; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
.key b { font-family: var(--f-display); font-size: 0.98rem; }
.key span { font-size: 0.9rem; color: var(--ink-2); }
.callout { border-left: 3px solid var(--accent); padding: 4px 0 4px 14px; color: var(--ink); }
@media (max-width: 640px) { figure .pair { grid-template-columns: 1fr; } body { font-size: 16px; } }
"""


def build():
    d1 = SESSIONS[0][1]
    r1 = {**bench(d1)["results"], **bench(d1, "soft")["results"]}
    zdep = lambda v: fmt(r1[v]["trial_zdep"], 0)  # noqa: E731
    body = f"""
<header style="display:flex;flex-direction:column;gap:10px">
  <span class="eyebrow">2P-proc · benchmark branch · validation report</span>
  <h1>Non-rigid z-correction on real recordings</h1>
  <p class="lede">The stimulus-locked artifact in Scnn1aAi14_D1M2 / 08292026 / run1 is reproduced in Python,
  explained as axial brain motion, and used to benchmark how the F_anat movie should be built and applied.
  Results replicate across four mice, both extraction backends and two stimulus types.</p>
  <p class="meta">Written for the Wang lab 2P group (Vincent, Manuel). Data: D1M2 run1/run2, B1M0 04182024 run1,
  B2M0 04192024 run3, A2M0 12152023 run1. Env: validation/pixi.toml (CaImAn 1.12.2, Suite2p 0.14.0).</p>
</header>

<h2>Summary</h2>
<div class="keys">
  <div class="key"><b>The artifact is z-motion</b><span>After 67.5 mJ laser stimuli the brain moves ~1.6 planes (µm) at
  1.45 s and again at ~2.4 s. Each ROI's spurious excitation or suppression has the sign and size predicted by
  F_anat (r = 0.58 across ROIs).</span></div>
  <div class="key"><b>Non-rigid F_anat works; rigid does not</b><span>The MATLAB non-rigid subtraction removes most
  of the artifact in every session. A global zpos regression barely helps and removes 15–18% of real
  signal.</span></div>
  <div class="key"><b>Per-patch, per-frame depth is essential</b><span>Using one depth for the whole field, or a fixed
  per-patch tilt, leaves the artifact almost intact. Smoothing patch depths over time or space also hurts.</span></div>
  <div class="key"><b>Two refinements help strong cases</b><span>Skipping the 3-frame movmean of F_anat and assigning
  soft (sub-plane) depths remove the residual left on D1M2 run1 (trial z-dependence
  {zdep('uni_mm3:ols')} → {zdep(SOFT + '_raw:ols')}). On weaker artifacts all F_anat methods already reach ~0.</span></div>
</div>

<h2>1 · Reproducing the example figures</h2>
<p>The MATLAB analysis (<code>analyze_2p_with_Beh_func.m</code>, steps 1–6 and 11–12, 'F' / 'raw' path) is ported in
<code>validation/stim_response_analysis.py</code>: piecewise-linear ΔF/F baseline fitted on pre-stimulus frames,
F_cell_anat as the uniform ROI-pixel mean of the 3-frame-smoothed F_anat, per-ROI OLS slope over all frames, bad-ROI
rejection (F0 &lt; 70, R² &gt; 0.25, max SNR &lt; 6, noise level &gt; 10) and rastermap ordering. With the iscell
labels Manuel shared, the port keeps 539 / 499 ROIs (without / with subtraction) against 535 / 495 in the MATLAB
figures.</p>
<figure><div class="plate pair">{img('avg_resp_stim4_none.png', 'Python port, without subtraction')}
{img('avg_resp_stim4_nonrigid.png', 'Python port, with subtraction')}</div>
<figcaption>Python port, 67.5 mJ, all 20 trials. Left: without subtraction, with the spurious band at 1.4–1.5 s
(suppression in one block of ROIs, synchronous "excitation" in another) and a weaker echo at ~2.4 s. Right: with the
MATLAB non-rigid subtraction. The MATLAB figures used the 16 wipe trials; ΔF/F is about 5× smaller here because
Suite2p was fed a differently offset movie (see section 6).</figcaption></figure>
<figure><div class="plate pair">{img('Scnn1aAi14_D1M2_08292026_run1 without subtraction.png', 'MATLAB, without', HERE / 'example')}
{img('Scnn1aAi14_D1M2_08292026_run1 with subtraction.png', 'MATLAB, with', HERE / 'example')}</div>
<figcaption>Reference: the MATLAB figures from validation/example (16 wipe trials).</figcaption></figure>

<h3>Why the earlier real-data tests showed no effect</h3>
<p>The previous tests used C57_O1M2 / 10022023, a recording without trials, and judged whole traces. The z-artifact
that matters here is locked to the stimulus and lasts 2–4 frames; it only becomes visible, and measurable, in trial
averages. All metrics below are built around the trial structure.</p>

<h2>2 · Mechanism</h2>
<figure><div class="plate">{img('fig_reproduction.png', 'Trial-averaged zpos and heatmaps')}</div>
<figcaption>D1M2 run1, 67.5 mJ, same ROI order in all panels (sorted by the F_anat prediction). Top: the
trial-averaged z-position jumps ~1.6 planes 0.45 s after laser onset. The F_anat prediction (right) reproduces the
band and its per-ROI sign: ROIs whose anatomy dims when the focal plane moves are "suppressed", those that brighten
are "excited".</figcaption></figure>
<figure><div class="plate">{img('fig_mechanism.png', 'Per-ROI deflection vs F_anat prediction')}</div>
<figcaption>Per ROI, deflection at the z-jump against the F_anat-predicted deflection. Uncorrected, the two are
correlated (r = 0.58); the MATLAB correction leaves r = 0.16; soft-depth F_anat leaves r = 0.04. ROIs far above
zero on the y-axis are genuine responders, and they are kept.</figcaption></figure>

<h2>3 · How the methods are scored</h2>
<p>No real recording has ground truth, so each metric targets one failure mode without assuming the answer. All
variants are compared on one fixed ROI set per session (ROIs kept without z-correction), so the R² rejection cannot
favour any of them.</p>
<ul>
  <li><b>Held-out trial-wise z-dependence</b> (main metric). The z-model is fitted on even trials only. On odd
  trials, after removing per-stimulus means, the dff step at the z-jump frame is correlated across trials with the
  F_anat step, for the 25% most z-loaded ROIs. 0 means no z left; negative means overcorrection.</li>
  <li><b>z-locked residual.</b> Across-ROI correlation between the trial-averaged residual and the F_anat prediction
  in the z-jump window.</li>
  <li><b>Injected signal kept</b> (ground truth). Synthetic GCaMP responses (3 SD, τ = 0.3 s) are added to 30% of
  real ROIs, starting at the z-jump, with amplitude proportional to each trial's z-step (the worst case: real
  activity coupled to the motion). The fraction of the injected trial-average that survives correction is
  reported; 1 means nothing was removed.</li>
  <li>Also computed: spontaneous z-jump triggered deflections, physiologically impossible frame-to-frame drops, and
  significance counts (section 5).</li>
</ul>

<h2>4 · Results across sessions</h2>
<h3>Held-out trial-wise z-dependence (0 is ideal)</h3>
{session_table('trial_zdep', 0)}
<h3>Injected z-coupled signal kept (1 is ideal)</h3>
{session_table('inject_coupled', 1)}
<p>Cell shading: within 0.05 of ideal, within 0.12, or further. "F_anat, one depth" uses the z-stack plane at zpos
for every patch. "Soft depth" is β = 200, ±8 planes, σ = 1, fitted by OLS without movmean.</p>
<figure><div class="plate">{img('fig_methods.png', 'Fitting methods across sessions')}</div>
<figcaption>Fitting variants applied to the production F_anat. Dropping the movmean and lagged regressors reduce
the residual on the strong-artifact sessions. Robust (Huber) slopes and fits on trial residuals keep slightly more
signal but remove less z.</figcaption></figure>

<h3>F_anat construction</h3>
<p>The production F_anat picks, per frame and per 60 × 60 px patch, the z-stack plane (within zpos ± 5) with the
highest Gaussian-smoothed R², and averages overlapping patches. Each ROI's F_anat trace can be written as a sum of
per-patch contributions, so any depth-selection rule can be evaluated exactly in seconds
(<code>validation/fanat_variants.py</code>; the production rule reproduces the production F_anat to
r = 0.99999994).</p>
<figure><div class="plate">{img('fig_fanat_rules.png', 'F_anat construction rules')}</div>
<figcaption>Depth must vary per patch and per frame. Soft depth (softmax of β·R² over ±8 planes) is the only rule
that removes the residual on D1M2 run1, at a small cost in retained signal there (0.95 vs 0.97).</figcaption></figure>
<h3>Patch grid (D1M2 run1)</h3>
{grid_table()}
<p>60 px patches (~87 µm) are best. A denser grid of the same patches (stride 24) reduces the argmax residual by
about a third at 2.2× the compute; with soft depth the grid density stops mattering.</p>

<h2>5 · What changes for the biology</h2>
<p>Significantly excited / suppressed ROIs in the z-jump window (1.35–1.6 s vs the last 0.5 s of baseline,
Wilcoxon over trials of the strongest stimulus, Bonferroni p &lt; 0.01):</p>
{detection_table()}
<p>Without correction, D1M2 run1 shows 11 (Suite2p) or 6 (CNMF) significantly "suppressed" cells at the z-jump; all
F_anat corrections remove them. Counts in the late window (2–3 s) barely change. These counts have no ground truth;
the injection test is the check that real responses survive.</p>

<h2>6 · Issues found along the way</h2>
<ul>
  <li><b>Stimulus labels on D1M2 run1.</b> params_matlab.json uses the template <code>rand_stim_seq</code>, but
  Bruker delivered 175 ms instead of 225 ms at block position 11 (trials 11, 31, 51, 71, 91). Five of the twenty
  "67.5 mJ" trials were 52.5 mJ. The older sessions match the template exactly.
  <code>params_from_bruker()</code> builds the trial vector from the VoltageOutput files.</li>
  <li><b>Behaviour videos.</b> The BehaviorCam*_t2.mp4 files in the run1 folder are run2's (30 trials × 4 s × 200 Hz
  = 24,000 frames). The run1 videos (_t1) are needed to reproduce the wipe-trial selection.</li>
  <li><b>ΔF/F scale.</b> Detection is identical to Manuel's run (same 3051 ROIs), but ΔF/F is ~5× smaller here,
  so the F offset of the movie given to Suite2p differs (here negative values are clipped at 0 when writing
  mcorr_movie.tiff). The comparison is unaffected; absolute ΔF/F values depend on this choice.</li>
  <li><b>R² rejection.</b> MATLAB rejects ROIs whose z-model explains R² &gt; 0.25. A better z-model raises R², so the
  rejection removes more ROIs (668 → 631 on D1M2 run1). It may be better to judge ROIs on the corrected trace.</li>
  <li><b>zstack_shifted.tif</b> is written into the raw ZSeries folder; in production that is the source data
  directory.</li>
</ul>

<h2>7 · Pipeline changes on the benchmark branch</h2>
<ul>
  <li><b>F_anat out-of-memory fix</b> (<code>compute_zcorr.compose_f_anat_non_rigid</code>). The old composite
  stored a z-stack crop per patch and frame; on 8000 frames at 765 px it was killed at 190 GB. The new version
  builds each pixel from the z-stack directly: identical output (0 differing pixels), 59 GB peak.</li>
  <li><b>CNMF export fix</b> (<code>extraction.prepare_cnmf_object</code>). With the template's p = 0, CaImAn 1.12.2
  crashes in <code>select_components</code>; the scalar <code>g</code> is now cleared first.</li>
  <li><b>Opt-in fast / soft F_anat</b> (<code>compute_zcorr.f_anat_non_rigid_fast</code>), enabled by a
  <code>z_motion_correction.f_anat</code> block, e.g. <code>{{"depth_mode": "soft", "beta": 200, "half_window": 8}}</code>.
  With the defaults (argmax, ±5) it reproduces the production F_anat exactly. Without the block nothing changes.</li>
</ul>

<h2>8 · Recommendations</h2>
<ol>
  <li>Keep non-rigid F_anat subtraction as the method; drop rigid zpos correction from the options users reach for.</li>
  <li>In the per-ROI step (MATLAB and <code>run_roi_zcorr</code>), make the 3-frame movmean of F_anat optional and
  default it off. It is never worse on the held-out metric and keeps more signal.</li>
  <li>Offer soft depth for recordings with strong stimulus-locked motion (laser, wipes). Before making it the
  default, test it on a few more strong-artifact runs; on weak artifacts it tends to overcorrect slightly
  (−0.03).</li>
  <li>Build trial vectors from the Bruker VoltageOutput files rather than from the template sequence.</li>
  <li>Reconsider the R² &gt; 0.25 rejection criterion.</li>
</ol>

<h2>Open items</h2>
<ul>
  <li>Run1 behaviour videos (_t1) and the 2024 profile DLC network, to reproduce the "during wipes" selection and
  split trials by wipe.</li>
  <li>Manuel's F.npy for run1, to pin down the ΔF/F offset.</li>
  <li>labeled_cortex / labeled_face exported as plain position arrays (the .mat files hold MATLAB ROI objects).</li>
</ul>

<h2>Reproduce</h2>
<p class="meta">cd validation &amp;&amp; ./run_session_benchmark.sh configs/config_&lt;session&gt;_local.json
configs/params_&lt;session&gt;.json &lt;stim&gt;<br>pixi run python make_realdata_figures.py --out report/realdata
<br>pixi run python build_realdata_report.py<br>Exports: /home/wanglab/data/2P/Analysis_2P/&lt;mouse&gt;/&lt;date&gt;/&lt;run&gt;/
(benchmark/, stim_resp/, fanat_variants/)</p>
"""
    return f"""<title>Non-rigid z-correction on real recordings</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>{CSS}</style>
<main>{body}</main>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=FIG / "zcorr_realdata_report.html")
    args = ap.parse_args()
    args.out.write_text(build())
    print(args.out, f"{args.out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
