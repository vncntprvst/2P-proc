"""Build the cell-registration validation report (single HTML page, figures embedded).

Usage: python validation/registration/build_registration_report.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build_realdata_report import CSS, img  # noqa: E402

FIG = HERE.parent / "report" / "registration"
M = [("caiman", "CaImAn (current)"), ("caiman_meanE", "CaImAn, meanE template"),
     ("track2p_affine", "Track2p affine"), ("track2p_nonrigid", "Track2p non-rigid"), ("roicat", "ROICaT")]


def load(name):
    return json.loads((HERE / name).read_text())


def fmt(v, d=3):
    return f"{v:.{d}f}" if isinstance(v, float) else str(v)


def splithalf_table():
    d = load("results_splithalf_D1M2run1.json")
    keys = [k for k in d if k.startswith("amp")]
    lab = {k: ("identical frame" if k == "amp0_rot0_shift0,0" else f"{k.split('_')[0][3:]} µm + rot/shift")
           for k in keys}
    head = "".join(f"<th>{lab[k]}</th>" for k in keys)
    rows = "".join(f"<tr><th scope='row'>{n}</th>" + "".join(
        f"<td class='num'>{d[k][m]['f1']:.3f}</td>" for k in keys) + "</tr>" for m, n in M)
    return f"<div class='tablewrap'><table><thead><tr><th>F1</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>"


def crossday_table():
    d, neg = load("results_crossday_D1M2.json"), load("results_negative_D1M2.json")
    fp = load("results_fingerprint_D1M2.json")
    cols = ["matches 2 d", "matches 5 d", "residual 5 d (µm)", "cycle consistency", "response r, match / neighbour (5 d)",
            "false matches (shifted)", "matches to other plane"]
    rows = []
    for m, n in M:
        f = fp[f"d0824:d0829 {m}"]
        other = d["d0829:d0828"][m]
        rows.append(
            f"<tr><th scope='row'>{n}</th>"
            f"<td class='num'>{d['d0829:d0831'][m]['n_matches']}</td><td class='num'>{d['d0824:d0829'][m]['n_matches']}</td>"
            f"<td class='num'>{d['d0824:d0829'][m]['residual_um']:.1f}</td>"
            f"<td class='num'>{d['cycle d0824:d0829:d0831'][m]['consistency']:.2f}</td>"
            f"<td class='num'>{f['r_match']:.3f} / {f['r_neighbour']:.3f}</td>"
            f"<td class='num'>{neg[m]['n_false_matches']}</td>"
            f"<td class='num'>{other.get('n_matches', 'refuses')}</td></tr>")
    head = "".join(f"<th>{c}</th>" for c in cols)
    return f"<div class='tablewrap'><table><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def build():
    sd = load("results_sameday_D1M2.json")
    sd_rows = "".join(f"<tr><th scope='row'>{n}</th><td class='num'>{sd['run1-run2'][m]['precision']:.3f}</td>"
                      f"<td class='num'>{sd['run1-run2'][m]['recall']:.3f}</td><td class='num'>{sd['run1-run2'][m]['f1']:.3f}</td>"
                      f"<td class='num'>{sd['run1-run2'][m]['time_s']:.0f}</td></tr>" for m, n in M)
    body = f"""
<header style="display:flex;flex-direction:column;gap:10px">
  <span class="eyebrow">2P-proc · benchmark branch · validation report</span>
  <h1>Tracking cells across sessions</h1>
  <p class="lede">Which method should the pipeline use to match the same neurons across separately processed
  sessions, and how reliable is it? Five methods were compared on one set of Suite2p footprints with three kinds of
  evidence: known deformations, a same-day reference and real cross-day data with controls.</p>
  <p class="meta">Written for the Wang lab 2P group (Vincent, Manuel). Data: Scnn1aAi14_D1M2, 08/24, 08/28, 08/29
  (run1, run2) and 08/31 2026; 16×, 765 × 765 px, 1.45 µm/px. Tools: CaImAn 1.12.2, Track2p 0.6.2, ROICaT 1.7.12.</p>
</header>

<h2>Summary</h2>
<div class="keys">
  <div class="key"><b>ROICaT is the pipeline default</b><span>Perfect recovery under known deformations up to
  10 µm, the most cross-day matches with the best cycle consistency (0.96), matched cells respond alike, and it
  refuses to match a different imaging plane.</span></div>
  <div class="key"><b>The current CaImAn path is weaker</b><span>It misses matches as deformation grows (F1 0.83
  at 10 µm), finds 11–22% fewer cross-day matches and has cycle consistency 0.81.</span></div>
  <div class="key"><b>Real deformation is small here</b><span>Across 2–5 days, matched cells sit within 0.9–1.9 µm
  of an affine fit. Non-rigid B-spline alignment (Track2p non-rigid) overfits on real cross-day images and fails.</span></div>
  <div class="key"><b>Segmentation limits tracking</b><span>Even within one recording, only 57–65% of iscell ROIs have
  a clear partner when the halves are segmented separately. Same-day runs should be processed jointly.</span></div>
</div>

<h2>1 · What existed</h2>
<p>Two registration paths existed and neither was used downstream. <code>Caiman/multisession_registration.py</code>
runs CaImAn <code>register_multisession</code> on CNMF outputs only; its <code>--json</code> mode cannot read current
configs and no parameter is exposed. The MATLAB CellReg wrapper cannot run (undefined variables, returns the
initial rather than the final map, relies on a fork-only API, nothing writes its inputs, CellReg is not installed).
In practice same-day runs are matched by concatenating them before processing.</p>

<h2>2 · Known deformations (split-half)</h2>
<p>Suite2p was run separately on the two halves (4000 frames each) of D1M2 run1, which share one motion-corrected
frame. Mutual best IoU ≥ 0.5 between the halves defines 370 reference pairs (ROIs with best IoU 0.2–0.5 are not
scored). The second half was then deformed with known smooth random fields (150 µm scale), a 1.5° rotation and a
13 µm shift, and every method had to recover the reference pairs.</p>
<figure><div class="plate">{img('fig_splithalf.png', 'Split-half F1 and recall vs deformation', FIG)}</div>
<figcaption>Precision stays above 0.92 for all methods; what fails is recall. Affine alignment cannot follow
non-rigid deformation; CaImAn's optical flow degrades gradually.</figcaption></figure>
{splithalf_table()}
<p>ROICaT misses 9% of pairs when the two frames are identical (no deformation at all), which does not occur with
real data.</p>

<h2>3 · Same day, against a joint reference</h2>
<p>Runs 1 and 2 of 08/29 were processed separately and jointly (concatenated). Each run's ROIs were mapped onto the
joint ROIs after a rigid shift (mutual best IoU ≥ 0.5); two ROIs that map to the same joint ROI form one of
{sd['run1-run2']['n_reference_pairs']} reference pairs.</p>
<div class="tablewrap"><table><thead><tr><th></th><th>precision</th><th>recall</th><th>F1</th><th>time (s)</th></tr></thead>
<tbody>{sd_rows}</tbody></table></div>
<p>All methods are near perfect: within a day the fields differ by a few pixels and ~1 µm of non-rigid motion.</p>

<h2>4 · Across days</h2>
<p>There is no ground truth across days, so each method is scored by self-consistency and controls:
cycle consistency over 08/24 → 08/29 → 08/31 against 08/24 → 08/31; centroid residual after an affine fit;
false matches when session-2 footprints are shifted by 60 µm while its image is kept (no true partner exists);
matches to 08/28, recorded at a different depth (stage Z 170.7 vs 160 µm, image correlation 0.20 after alignment);
and response similarity of matched cells (laser responses) against their nearest non-matched neighbour.</p>
<figure><div class="plate">{img('fig_crossday.png', 'Cross-day metrics per method', FIG)}</div></figure>
{crossday_table()}
<figure><div class="plate">{img('fig_fingerprint.png', 'Functional fingerprint', FIG)}</div>
<figcaption>Matched cells respond more alike than their nearest non-matched neighbours for every method except
Track2p non-rigid, whose 5-day matches are at chance. Responses drift across days, so the absolute values are
low.</figcaption></figure>
<p>A left-right flipped session was also tried as a control and discarded: ROICaT's image aligner can undo a
mirror image and then matches correctly (307 matches), so a flip is not a valid negative for it. The false matches
in the shifted-footprint control are a floor for dense fields when no true partner exists; with true partners
present (sections 2 and 3) precision stays above 0.92.</p>

<h2>5 · In the pipeline</h2>
<p><code>python -m pipeline.register_sessions --exports &lt;day1&gt; &lt;day2&gt; ... --out &lt;dir&gt; --method roicat</code>
(module <code>modules/cell_registration.py</code>). Inputs are Suite2p iscell ROIs or CNMF components and the mean
images. Outputs: <code>cell_registration.npz/.mat</code> with the cells × sessions ROI indices in extraction order
(1-based in the .mat, 0 = absent), <code>cell_registration_qc.json</code> (matches and affine residual per
session pair, FOV similarity with a warning below 0.5) and a QC figure. ROICaT needs Python ≥ 3.11, so it runs in
its own environment (<code>--python</code> or <code>$ROICAT_PYTHON</code>), like Suite2p in production.</p>
<figure><div class="plate">{img('fig_qc_example.png', 'QC figure', FIG)}</div>
<figcaption>ROICaT on 08/24, 08/29 and 08/31: 179 cells tracked in all three sessions, 585 in at least two.</figcaption></figure>

<h2>6 · Recommendations</h2>
<ol>
  <li>Use ROICaT for cross-day registration; keep Track2p affine as a lighter alternative and CaImAn for
  compatibility. Do not use non-rigid B-spline alignment across days.</li>
  <li>Process runs from the same day and field jointly (concatenated). Separately processed short runs segment
  inconsistently (on B2M0 04/22, 262 to 4745 Suite2p ROIs per 1600-frame run).</li>
  <li>Check the QC: FOV similarity below 0.5 means a different field or plane; affine residuals above ~3 µm or a
  low tracked fraction call for a look at the images.</li>
  <li>Retire <code>Caiman/multisession_registration.py</code> and the MATLAB CellReg wrapper.</li>
</ol>

<h2>Limits and open items</h2>
<ul>
  <li>One mouse with a same-FOV series; the cross-day evidence is indirect. Blinded manual annotation of a sample of
  ROIs (with the mean images and z-stacks) would give a direct cross-day error rate.</li>
  <li>The tdTomato channel at this depth is diffuse (no labelled somata), so it could not anchor true pairs.</li>
  <li>Pipeline movies are vertically flipped relative to the raw Bruker frames; overlays of raw data (red channel,
  z-stacks) must account for it.</li>
  <li>ROICaT's degenerate-case error (different plane) should be caught and reported as "not the same field".</li>
</ul>

<h2>Reproduce</h2>
<p class="meta">cd validation; pixi run python registration/bench_splithalf.py &lt;half1&gt; &lt;half2&gt; --out ...<br>
pixi run python registration/bench_sameday.py --runs &lt;run1&gt; &lt;run2&gt; --joint &lt;run1run2&gt; --out ...<br>
pixi run python registration/bench_crossday.py --sessions ... --pairs ... --triplets ... --out ...<br>
pixi run python registration/negative_control.py &lt;plane1&gt; &lt;plane2&gt; --out ...<br>
python3 registration/make_registration_figures.py; python3 registration/build_registration_report.py</p>
"""
    return f"""<title>Tracking cells across sessions</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>{CSS}</style>
<main>{body}</main>
"""


if __name__ == "__main__":
    out = FIG / "registration_report.html"
    out.write_text(build())
    print(out)
