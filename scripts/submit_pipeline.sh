#!/bin/bash
# submit_pipeline.sh — orchestrator that chains the three pipeline SLURM steps
# via --dependency=afterok job chaining.
#
# Usage:
#   bash submit_pipeline.sh path/to/config.json [--skip-mcorr] [--skip-extract] [--mail-user EMAIL]
#
# Steps submitted (unless skipped):
#   1. sbatch_nonrigid_mcorr.sh   — non-rigid motion correction
#   2. sbatch_aind_extraction.sh  — AIND Suite2p extraction
#   3. sbatch_roi_zcorr.sh        — ROI z-motion correction
#
# Flags:
#   --skip-mcorr     Skip step 1; steps 2 and 3 run (3 depends on 2).
#   --skip-extract   Skip step 2; step 3 runs immediately after step 1
#                    (or immediately if --skip-mcorr is also set).
#   --mail-user EMAIL  Passed through to each sbatch call.

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

CONFIG_FILE=""
SKIP_MCORR=0
SKIP_EXTRACT=0
MAIL_USER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-mcorr)
            SKIP_MCORR=1
            shift
            ;;
        --skip-extract)
            SKIP_EXTRACT=1
            shift
            ;;
        --mail-user)
            MAIL_USER="$2"
            shift 2
            ;;
        --mail-user=*)
            MAIL_USER="${1#--mail-user=}"
            shift
            ;;
        --*)
            die "Unknown option: $1"
            ;;
        *)
            if [ -z "$CONFIG_FILE" ]; then
                CONFIG_FILE="$1"
            else
                die "Unexpected positional argument: $1"
            fi
            shift
            ;;
    esac
done

if [ -z "$CONFIG_FILE" ]; then
    echo "Usage: bash submit_pipeline.sh path/to/config.json [--skip-mcorr] [--skip-extract] [--mail-user EMAIL]"
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    die "Config file not found: $CONFIG_FILE"
fi

# Resolve the config path to an absolute path so downstream scripts are not
# confused by relative paths when they cd into different directories.
CONFIG_FILE="$(realpath "$CONFIG_FILE")"

# ---------------------------------------------------------------------------
# Locate the scripts directory (same directory as this script)
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure slurm_logs/ exists beside the scripts
mkdir -p "$SCRIPT_DIR/slurm_logs"

# ---------------------------------------------------------------------------
# Build shared sbatch options
# ---------------------------------------------------------------------------

# Extra options forwarded to every sbatch call
SBATCH_EXTRA=()
if [ -n "$MAIL_USER" ]; then
    SBATCH_EXTRA+=("--mail-user=$MAIL_USER")
fi

# ---------------------------------------------------------------------------
# Validate that sbatch is available
# ---------------------------------------------------------------------------

if ! command -v sbatch >/dev/null 2>&1; then
    die "sbatch not found. This script must run on a SLURM submit node."
fi

# ---------------------------------------------------------------------------
# Helper: submit a step and return its job ID
# ---------------------------------------------------------------------------

submit_step() {
    local script="$1"
    shift
    local dep_flag="${1:-}"     # e.g. "--dependency=afterok:12345" or ""
    shift 2>/dev/null || true   # might be empty

    local sbatch_args=()
    [ -n "$dep_flag" ] && sbatch_args+=("$dep_flag")
    sbatch_args+=("${SBATCH_EXTRA[@]+"${SBATCH_EXTRA[@]}"}")

    local cmd=(sbatch "${sbatch_args[@]}" "$SCRIPT_DIR/$script" "$CONFIG_FILE")
    echo "Submitting: ${cmd[*]}"
    local output
    output=$("${cmd[@]}")
    echo "$output"
    # sbatch prints "Submitted batch job <id>"
    echo "$output" | awk '{print $NF}'
}

# ---------------------------------------------------------------------------
# Step 1: Non-rigid motion correction
# ---------------------------------------------------------------------------

MCORR_JOB=""
if [ "$SKIP_MCORR" -eq 0 ]; then
    echo ""
    echo "--- Step 1: Non-rigid motion correction ---"
    MCORR_JOB=$(submit_step "sbatch_nonrigid_mcorr.sh" "")
    echo "  Job ID: $MCORR_JOB"
else
    echo ""
    echo "--- Step 1: Non-rigid motion correction --- SKIPPED (--skip-mcorr)"
fi

# ---------------------------------------------------------------------------
# Step 2: AIND extraction
# ---------------------------------------------------------------------------

EXTRACT_JOB=""
if [ "$SKIP_EXTRACT" -eq 0 ]; then
    echo ""
    echo "--- Step 2: AIND extraction ---"
    if [ -n "$MCORR_JOB" ]; then
        EXTRACT_JOB=$(submit_step "sbatch_aind_extraction.sh" "--dependency=afterok:$MCORR_JOB")
    else
        # No mcorr job to wait for — submit immediately
        EXTRACT_JOB=$(submit_step "sbatch_aind_extraction.sh" "")
    fi
    echo "  Job ID: $EXTRACT_JOB"
else
    echo ""
    echo "--- Step 2: AIND extraction --- SKIPPED (--skip-extract)"
fi

# ---------------------------------------------------------------------------
# Step 3: ROI z-motion correction
# ---------------------------------------------------------------------------

echo ""
echo "--- Step 3: ROI z-motion correction ---"

# Determine what step 3 depends on
if [ -n "$EXTRACT_JOB" ]; then
    ZCORR_DEP="--dependency=afterok:$EXTRACT_JOB"
elif [ -n "$MCORR_JOB" ]; then
    # extract was skipped but mcorr ran
    ZCORR_DEP="--dependency=afterok:$MCORR_JOB"
else
    # Both upstream steps were skipped — submit immediately
    ZCORR_DEP=""
fi

ZCORR_JOB=$(submit_step "sbatch_roi_zcorr.sh" "$ZCORR_DEP")
echo "  Job ID: $ZCORR_JOB"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "============================================="
echo "Pipeline submission summary"
echo "============================================="
echo "  Config:              $CONFIG_FILE"
if [ -n "$MCORR_JOB" ]; then
    echo "  Step 1 (mcorr):      job $MCORR_JOB"
else
    echo "  Step 1 (mcorr):      SKIPPED"
fi
if [ -n "$EXTRACT_JOB" ]; then
    echo "  Step 2 (extraction): job $EXTRACT_JOB  [afterok:${MCORR_JOB:-<none>}]"
else
    echo "  Step 2 (extraction): SKIPPED"
fi
echo "  Step 3 (roi_zcorr):  job $ZCORR_JOB  [${ZCORR_DEP:-no dependency}]"
echo "============================================="
echo ""
echo "Monitor with:  squeue -j $MCORR_JOB,$EXTRACT_JOB,$ZCORR_JOB"
echo ""
