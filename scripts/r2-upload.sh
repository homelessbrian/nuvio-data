#!/usr/bin/env bash
# Copies sports files to the Cloudflare R2 bucket the app reads them from (through the livetv-cloud
# Worker, for our own apps only).
#
#   scripts/r2-upload.sh changed   files staged in git (added/changed are uploaded, deleted are removed)
#   scripts/r2-upload.sh all       every file (first fill, or to repair the bucket)
#
# Needs the secrets R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_ENDPOINT. Without them it does
# nothing, so the job keeps working as before. Optional variable R2_BUCKET (default nuvio-sports).
# A failure here never stops the job: the files are still saved in this repo.
set -uo pipefail

if [ -z "${R2_ACCESS_KEY_ID:-}" ] || [ -z "${R2_SECRET_ACCESS_KEY:-}" ] || [ -z "${R2_ENDPOINT:-}" ]; then
  echo "R2 secrets not set: nothing copied to R2."
  exit 0
fi

BUCKET="${R2_BUCKET:-nuvio-sports}"
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION=auto AWS_EC2_METADATA_DISABLED=true
# R2 doesn't take every checksum newer AWS tools add by default.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
S3="aws s3 --endpoint-url ${R2_ENDPOINT%/} --only-show-errors"
WANTED='^(sportsdb|espn|football)/.*\.json$'

stage=$(mktemp -d)
removed=$(mktemp)
case "${1:-changed}" in
  all)
    git ls-files | grep -E "$WANTED" | while read -r f; do [ -f "$f" ] && cp --parents "$f" "$stage/"; done
    ;;
  changed)
    git diff --cached --name-status --no-renames | while IFS=$'\t' read -r status f; do
      echo "$f" | grep -qE "$WANTED" || continue
      if [ "$status" = "D" ]; then echo "$f" >> "$removed"; elif [ -f "$f" ]; then cp --parents "$f" "$stage/"; fi
    done
    ;;
  *) echo "Usage: $0 changed|all"; exit 1 ;;
esac

count=$(find "$stage" -type f | wc -l)
if [ "$count" -gt 0 ]; then
  if $S3 cp "$stage" "s3://$BUCKET/" --recursive --content-type "application/json; charset=utf-8" --cache-control "no-cache"; then
    echo "Copied $count file(s) to R2."
  else
    echo "::warning::Copying $count file(s) to R2 failed."
  fi
else
  echo "No files to copy to R2."
fi

gone=0
while read -r f; do
  [ -n "$f" ] || continue
  $S3 rm "s3://$BUCKET/$f" < /dev/null && gone=$((gone + 1))
done < "$removed"
[ "$gone" -gt 0 ] && echo "Removed $gone file(s) from R2."

rm -rf "$stage" "$removed"
exit 0
