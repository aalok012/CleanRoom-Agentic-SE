#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run_example.sh — end-to-end CLEANROOM-AGENT demo on a single SRS.
#
# Runs the full pipeline (contracts → dependency → planning → clean-room
# proof/code/test generation → proof-guided + pass@k certification) on ONE
# specification and prints where the per-requirement audit labels landed.
#
# Usage:
#   ./run_example.sh                       # default: Human.xml, python, DeepSeek
#   MODEL=openai/gpt-5.1 ./run_example.sh  # pick a model (routed via OpenRouter)
#   SRS="data/srs/dineout_srs.xml" LANG=java ./run_example.sh
#
# Requires: uv (https://docs.astral.sh/uv/) and an OpenRouter or OpenAI key.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

# ---- config (override via environment) --------------------------------------
SRS="${SRS:-data/srs/Human.xml}"          # smallest subject (2 FRs) → fast demo
MODEL="${MODEL:-deepseek/deepseek-v3.2}"  # cheapest model in the study
LANG="${LANG:-python}"                     # python | java | javascript
STRATEGY="${STRATEGY:-mot}"                # baseline | cot | mot
OUT="${OUT:-outputs/example}"

# ---- preflight --------------------------------------------------------------
if [ ! -f .env ] && [ -z "${OPENROUTER_API_KEY:-}${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: no API key found. Create a .env with:"
  echo "    OPENROUTER_API_KEY=sk-or-..."
  echo "  (or export OPENROUTER_API_KEY / OPENAI_API_KEY in your shell)."
  exit 1
fi
[ -f .env ] && set -a && . ./.env && set +a || true

echo "════════════════════════════════════════════════════════════════"
echo " CLEANROOM-AGENT — single-example run"
echo "   SRS        : $SRS"
echo "   model      : $MODEL"
echo "   language   : $LANG"
echo "   strategy   : $STRATEGY"
echo "   output dir : $OUT"
echo "════════════════════════════════════════════════════════════════"

# ---- run the full pipeline (proof-guided + pass@k certification) -------------
uv run python run_pipeline.py "$SRS" \
  --model "$MODEL" \
  --language "$LANG" \
  --prompt-strategy "$STRATEGY" \
  --prove --certify \
  --output-dir "$OUT"

echo ""
echo "Done. Per-requirement audit labels and metrics are in:"
echo "   $OUT/  (see the *_run_report.md and runs/*.json for this run)"
