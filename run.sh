#!/usr/bin/env bash
# Signalpost — one-command run.
# Usage: ./run.sh [organisations.jsonl] [output-dir]
# Defaults: the bundled 100-company smoke list, out/
set -euo pipefail
cd "$(dirname "$0")"

ORGS="${1:-data/smoke-companies.jsonl}"
OUT="${2:-out}"
BULK="${BULK:-data/brreg-enheter.csv}"

if ! command -v python3 >/dev/null; then
  echo "python3 (3.12+) is required" >&2; exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

mkdir -p "$OUT" data

# Frozen Brønnøysund bulk snapshot (public data, ~155 MB gzipped).
# Download once if not present; the official run reuses the same file.
if [ ! -s "$BULK" ]; then
  echo "Downloading Brreg bulk snapshot to $BULK ..."
  curl -L 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o "$BULK"
fi

.venv/bin/python scripts/run_competition_batch.py \
  --organisations "$ORGS" \
  --bulk "$BULK" \
  --profiles-output "$OUT/profiles.jsonl" \
  --output "$OUT/envelopes.jsonl" \
  --report "$OUT/report.json" \
  --run-id "${RUN_ID:-signalpost-run}" \
  --resume \
  --expected-count "${EXPECTED_COUNT:-100}"
