#!/usr/bin/env bash
# Full real-data benchmark for one session: pipeline (mcorr + F_anat + Suite2p), MATLAB-port
# response figure, F_anat projections, patch depth profiles, F_anat rule variants, soft sweep,
# z-correction benchmarks and response detection.
#
# Usage: validation/run_session_benchmark.sh <config.json> <params.json> <stim> [--skip-pipeline]
set -euo pipefail
CONFIG=$(realpath "$1")
PARAMS=$(realpath "$2")
STIM=$3
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT/validation"
read -r EXPORT ZDIR STRIDES OVERLAPS <<<"$(python3 -c "
import json,sys; c=json.load(open(sys.argv[1]))
m=c['params_mcorr']['main']
print(c['paths']['export_paths'][0], c['paths']['zstack_paths'][0], m['strides'][0], m['overlaps'][0])" "$CONFIG")"
mkdir -p "$EXPORT"
if [ "${4:-}" != "--skip-pipeline" ]; then
    ./run_local_pipeline.sh "$CONFIG" "$EXPORT"
fi
FANAT=$(ls "$EXPORT"/F_anat_non_rigid_T_*.tiff | head -1)
MMAP=$(ls "$EXPORT"/*/*.mmap | head -1)
pixi run python stim_response_analysis.py "$EXPORT" --out "$EXPORT/stim_resp" --stim "$STIM" --params "$PARAMS"
pixi run python - "$EXPORT" "$FANAT" <<'EOF'
import sys
import numpy as np
from stim_response_analysis import load_extraction, f_cell_anat_variants
exp, fanat = sys.argv[1:]
F, Fn, rois, lams = load_extraction(exp, with_lam=True)
uni, lam = f_cell_anat_variants(fanat, rois, lams)
np.savez(f"{exp}/stim_resp/F_cell_anat_variants.npz", uniform=uni, lam=lam)
EOF
NF=$(python3 -c "import json,sys; p=json.load(open(sys.argv[1])); print(round(p.get('fr',20)*p.get('trial_duration',4)))" "$PARAMS")
pixi run python fanat_variants.py profiles "$MMAP" "$ZDIR/zstack_shifted.tif" "$EXPORT/z_correlation.npz" \
    "$EXPORT" --out "$EXPORT/fanat_variants" --strides "$STRIDES" --overlaps "$OVERLAPS"
pixi run python fanat_variants.py variants "$EXPORT/fanat_variants" --nf-trial "$NF"
pixi run python fanat_variants.py soft "$EXPORT/fanat_variants"
B="pixi run python real_zcorr_benchmark.py $EXPORT --out $EXPORT/benchmark --params $PARAMS --stim $STIM"
$B
$B --rules "$EXPORT/fanat_variants/f_cell_anat_rules.npz" --tag rules
$B --rules "$EXPORT/fanat_variants/f_cell_anat_soft_sweep.npz" --tag soft
pixi run python response_detection.py "$EXPORT" --soft "$EXPORT/fanat_variants/f_cell_anat_soft_sweep.npz" \
    --params "$PARAMS" --stim "$STIM"
