#!/usr/bin/env bash
# Run the production chain locally (pixi env): motion correction + z-motion (F_anat),
# then Suite2p extraction on the exported mcorr_movie.tiff, as in scripts/2P_proc_template.sh.
#
# Usage: validation/run_local_pipeline.sh <config.json> <export_dir>
set -euo pipefail
CONFIG=$(realpath "$1")
EXPORT=$2
ROOT=$(cd "$(dirname "$0")/.." && pwd)
S2P=$ROOT/containers/suite2p/context/scripts
cd "$ROOT/validation"

pixi run bash -c "cd $ROOT && python -m pipeline.pipeline_mcorr $CONFIG"

if [ ! -f "$EXPORT/mcorr_movie.tiff" ]; then
    MMAP=$(ls "$EXPORT"/*/*.mmap | head -1)
    pixi run python -c "
from pathlib import Path
import sys; sys.path.insert(0, '$ROOT')
from modules.motion_correction import save_movie_as_tiff
save_movie_as_tiff(Path('$MMAP'), Path('$EXPORT/mcorr_movie.tiff'))"
fi

OPS=$(pixi run python "$ROOT/containers/2p_proc/context/paths_params_io.py" "$CONFIG" \
    --get-suite2p-ops --export-path "$EXPORT" | tail -1)
read -r NF LY LX FS TAU <<<"$(python3 -c "import json,sys; o=json.loads(sys.argv[1]); print(o['nframes'],o['Ly'],o['Lx'],o['fs'],o['tau'])" "$OPS")"
OVR=$(python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1])['ops_overrides']))" "$OPS")

pixi run python "$S2P/make_ops.py" --export_path "$EXPORT" --movie "$EXPORT/mcorr_movie.tiff" \
    --nframes "$NF" --Ly "$LY" --Lx "$LX" --fs "$FS" --tau "$TAU" --ops_overrides_json "$OVR" \
    --save_mat 1 --do_registration 0 --nonrigid 0 --zcorr_file "$EXPORT/z_correlation.npz"
pixi run python "$S2P/run_suite2p_api.py" --ops "$EXPORT/ops.npy"
