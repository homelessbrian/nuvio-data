#!/usr/bin/env bash
# Gets the ESPN score files the livetv-cloud Worker saved to R2 (it asks ESPN itself every 5
# minutes now), so this job only has to make the ready-made files and keep the copies in this repo.
#
# Writes "worker=true" to $GITHUB_OUTPUT when the Worker's last round was good and recent (under
# 15 minutes old); otherwise "worker=false", and the job asks ESPN itself (scripts/espn.py) as before.
# Needs the same R2 secrets as r2-upload.sh. Never fails the job.
set -uo pipefail
out="${GITHUB_OUTPUT:-/dev/stdout}"

if [ -z "${R2_ACCESS_KEY_ID:-}" ] || [ -z "${R2_SECRET_ACCESS_KEY:-}" ] || [ -z "${R2_ENDPOINT:-}" ]; then
  echo "R2 secrets not set: asking ESPN here."
  echo "worker=false" >> "$out"
  exit 0
fi

BUCKET="${R2_BUCKET:-nuvio-sports}"
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION=auto AWS_EC2_METADATA_DISABLED=true
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
S3="aws s3 --endpoint-url ${R2_ENDPOINT%/} --only-show-errors"

if ! $S3 cp "s3://$BUCKET/espn/_state.json" espn/_state.json; then
  echo "No Worker round found in R2: asking ESPN here."
  echo "worker=false" >> "$out"
  exit 0
fi

if ! python3 - <<'EOF'
import json, sys, time
try:
    run = json.load(open("espn/_state.json")).get("lastRun") or {}
except Exception:
    sys.exit(1)
age = time.time() - run.get("at", 0) / 1000
print("Worker's last ESPN round: %d min ago, %s, %s asked, %s saved" % (age // 60, "good" if run.get("ok") else "bad", run.get("asked"), run.get("written")))
sys.exit(0 if run.get("ok") and age < 15 * 60 else 1)
EOF
then
  echo "The Worker's last round is old or went badly: asking ESPN here."
  echo "worker=false" >> "$out"
  exit 0
fi

# The league files (not the ready-made ones, which this job makes, nor the round notes).
if ! $S3 cp "s3://$BUCKET/espn/" espn/ --recursive --exclude "*" --include "*.json" --exclude "compact/*" --exclude "_state.json"; then
  echo "::warning::Getting the Worker's files from R2 failed: asking ESPN here."
  git checkout -- espn 2>/dev/null || true
  echo "worker=false" >> "$out"
  exit 0
fi

# The Worker only saves a file when its games changed; when each day was last asked for is in
# _state.json. Put those times in the files, so the ready-made files and the copies in this repo
# (read by older apps) show how fresh each day really is.
python3 scripts/espn_stamps.py
echo "worker=true" >> "$out"
