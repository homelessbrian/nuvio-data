#!/usr/bin/env bash
# Where the jobs keep their sports files between runs.
#
# The repo variable PUBLIC_FILES decides (Settings > Secrets and variables > Actions > Variables):
#   not set, or anything but "off"   The files are saved in this (public) repo, as always.
#   off                              The files are NOT kept in this repo. Each job keeps them in one
#                                    packed file in the R2 bucket (_state/<job>.tar.gz, which the
#                                    Worker never hands out), and the copies in this repo are removed.
# Setting it back (delete the variable, or set it to "on") puts the files back in this repo on the
# job's next run.
#
#   scripts/state.sh get espn|tsdb   Start of a job: brings the files in when they aren't in the repo.
#                                    Writes "private=true|false" to $GITHUB_OUTPUT.
#   scripts/state.sh put espn|tsdb   End of a job, only when "private" was true: copies what changed
#                                    to R2 (scripts/r2-upload.sh), saves the packed file, and removes
#                                    the copies from this repo if they are still there.
#   scripts/state.sh get all         For the "Copy all sports files to R2" job.
#
# "off" needs the R2 secrets (R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT). Without them
# the files stay in this repo whatever the variable says.
set -uo pipefail

action="${1:-}"
job="${2:-}"
out="${GITHUB_OUTPUT:-/dev/stdout}"

# OWN    what the job's packed file holds
# TRACK  what the job saves at the end (the same paths its "Save what changed" step adds)
# CHECK  a file that is there whenever the job's files are
# KEEP   files that stay in this repo either way (wrestling.json: the app still asks this repo for
#        it now and then, so it is saved here as before)
case "$job" in
  espn) OWN="espn";              TRACK="espn sportsdb/4546.json"; CHECK="espn/compact/index.json"; KEEP="" ;;
  tsdb) OWN="sportsdb football"; TRACK="sportsdb football";       CHECK="sportsdb/index.json";     KEEP="wrestling.json" ;;
  all)  OWN="";                  TRACK="espn sportsdb football";  CHECK="";                        KEEP="" ;;
  *) echo "Usage: $0 get|put espn|tsdb"; exit 1 ;;
esac
# A file both jobs write (EuroLeague: the daily job makes it, the ESPN job adds live scores).
SHARED="sportsdb/4546.json"

have_r2=true
if [ -z "${R2_ACCESS_KEY_ID:-}" ] || [ -z "${R2_SECRET_ACCESS_KEY:-}" ] || [ -z "${R2_ENDPOINT:-}" ]; then have_r2=false; fi
BUCKET="${R2_BUCKET:-nuvio-sports}"
export AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:-}" AWS_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:-}"
export AWS_DEFAULT_REGION=auto AWS_EC2_METADATA_DISABLED=true
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
ENDPOINT="${R2_ENDPOINT:-}"
S3="aws s3 --endpoint-url ${ENDPOINT%/} --only-show-errors"

TMP="${RUNNER_TEMP:-/tmp}"
SHADOW="$TMP/nuvio-state-$job"          # a throwaway git folder, only used to see what a run changed
NEED_PACK="$TMP/nuvio-state-$job.pack"  # there when the packed file has to be saved even if nothing changed

private=false
if [ "${PUBLIC_FILES:-}" = "off" ]; then
  if $have_r2; then private=true; else echo "::warning::PUBLIC_FILES is off but the R2 secrets are missing: the files stay in this repo."; fi
fi

# Are this job's files still kept in the repo? (The shared file alone doesn't count.)
in_repo() {
  [ -n "$(git ls-files -- $1 | grep -v "^$SHARED\$" | head -1)" ]
}

# Brings one job's files in from R2: its packed file, or (if that is missing or broken) the
# separate files the apps read.
fetch_job() {
  local j="$1" own="$2" check="$3" pack="$TMP/nuvio-state-$1.tar.gz" ok=false
  rm -f "$pack"
  if $S3 cp "s3://$BUCKET/_state/$j.tar.gz" "$pack" && tar -xzf "$pack" -C . && [ -f "$check" ]; then
    ok=true
    echo "Got the $j files (packed file)."
  else
    echo "No usable packed file for $j: getting the separate files from R2."
    local d
    for d in $own; do $S3 cp "s3://$BUCKET/$d/" "$d/" --recursive || true; done
    if [ -f "$check" ]; then
      ok=true
      : > "$TMP/nuvio-state-$j.pack"
      echo "Got the $j files (separate files)."
    fi
  fi
  rm -f "$pack"
  $ok
}

# The newest copy of the file both jobs write.
fetch_shared() {
  local t="$TMP/nuvio-shared.json"
  rm -f "$t"
  if $S3 cp "s3://$BUCKET/$SHARED" "$t" 2>/dev/null && [ -s "$t" ]; then
    mkdir -p "$(dirname "$SHARED")"
    mv "$t" "$SHARED"
  fi
  rm -f "$t"
}

shadow_git() { GIT_DIR="$SHADOW/.git" GIT_WORK_TREE="$PWD" git "$@"; }

# Remembers the files as they are now, so the end of the run can tell what changed.
shadow_start() {
  rm -rf "$SHADOW"
  git init -q "$SHADOW"
  local p
  for p in $TRACK; do if [ -e "$p" ]; then shadow_git add -A -- "$p"; fi; done
  shadow_git -c user.name=state -c user.email=state@localhost commit -q --allow-empty -m start
}

# Brings this repo in line: the job's files out of it, and the files that stay here (KEEP) saved
# as before. Done in a separate clean copy of the repo, so nothing in the run's folder gets in the way.
update_repo() {
  local w="$TMP/nuvio-public-$job" try here="$PWD" k
  for try in 1 2 3; do
    git worktree remove --force "$w" 2>/dev/null; rm -rf "$w"; git worktree prune
    git fetch -q --depth 1 origin main || { sleep 5; continue; }
    git worktree add -q --detach "$w" FETCH_HEAD || { sleep 5; continue; }
    if (
      cd "$w" || exit 1
      git rm -r -q --ignore-unmatch -- $TRACK
      msg="Schedule update"
      if ! git diff --cached --quiet; then msg="Sports files are no longer kept here"; fi
      for k in $KEEP; do if [ -f "$here/$k" ]; then cp "$here/$k" "$k" && git add -- "$k"; fi; done
      if git diff --cached --quiet; then exit 0; fi
      git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
        commit -q -m "$msg"
      git push -q origin HEAD:main
    ); then
      git worktree remove --force "$w" 2>/dev/null
      return 0
    fi
    sleep 5
  done
  git worktree remove --force "$w" 2>/dev/null
  echo "::warning::Could not update this repo this time; the next run tries again."
  return 1
}

case "$action" in
  get)
    if [ "$job" = "all" ]; then
      # "Copy all sports files to R2": with the files out of the repo there is nothing to copy from
      # here, so bring both jobs' files in and let r2-upload.sh see them.
      if in_repo "espn sportsdb football" || ! $have_r2; then echo "private=false" >> "$out"; exit 0; fi
      fetch_job espn "espn" "espn/compact/index.json"
      fetch_job tsdb "sportsdb football" "sportsdb/index.json"
      fetch_shared
      shadow_start
      echo "private=true" >> "$out"
      exit 0
    fi

    rm -f "$NEED_PACK"
    if in_repo "$OWN"; then
      # The other job may already have taken the file both write out of the repo.
      if $have_r2 && [ ! -e "$SHARED" ]; then fetch_shared; fi
      if $private; then
        echo "PUBLIC_FILES is off: the $job files move out of this repo at the end of this run."
        : > "$NEED_PACK"
      fi
    elif ! $have_r2; then
      echo "The $job files aren't in this repo and the R2 secrets are missing: starting from nothing."
    else
      # Not in the repo: kept in R2 (PUBLIC_FILES off), or coming back (PUBLIC_FILES on again).
      if ! fetch_job "$job" "$OWN" "$CHECK"; then
        echo "::error::Could not get the $job files from R2. Stopping here so nothing is lost; the next run tries again."
        exit 1
      fi
      fetch_shared
      if ! $private; then echo "PUBLIC_FILES is on: the $job files go back into this repo at the end of this run."; fi
    fi
    if $private; then shadow_start; fi
    echo "private=$private" >> "$out"
    ;;

  put)
    if ! $private || [ ! -d "$SHADOW/.git" ]; then
      echo "::error::state.sh put is only for runs that started with PUBLIC_FILES off."
      exit 1
    fi
    for p in $TRACK; do if [ -e "$p" ]; then shadow_git add -A -- "$p"; fi; done
    changed=false
    if shadow_git diff --cached --quiet; then
      echo "No changes to save."
    else
      changed=true
      # The changed files, to the R2 bucket our apps read them from.
      GIT_DIR="$SHADOW/.git" GIT_WORK_TREE="$PWD" bash scripts/r2-upload.sh changed
    fi

    packed=true
    if $changed || [ -e "$NEED_PACK" ]; then
      packed=false
      pack="$TMP/nuvio-state-$job.tar.gz"
      have=""
      for p in $OWN; do if [ -e "$p" ]; then have="$have $p"; fi; done
      if [ -f "$CHECK" ] && tar -czf "$pack" --exclude="espn/_state.json" $have \
        && $S3 cp "$pack" "s3://$BUCKET/_state/$job.tar.gz" --content-type "application/gzip"; then
        packed=true
        rm -f "$NEED_PACK"
        echo "Saved the packed $job files ($(du -h "$pack" | cut -f1))."
      else
        echo "::warning::Saving the packed $job files failed; the next run starts from the last good one."
      fi
      rm -f "$pack"
    fi

    # Only once the packed file is safely saved: take the copies out of this repo.
    still_here=false
    if [ -n "$(git ls-files -- $TRACK | head -1)" ]; then still_here=true; fi
    if $still_here && ! $packed; then
      echo "Leaving the files in this repo until the packed file is saved."
      exit 0
    fi
    keep_changed=false
    for k in $KEEP; do if [ -f "$k" ] && ! git diff --quiet HEAD -- "$k" 2>/dev/null; then keep_changed=true; fi; done
    if [ -n "$KEEP" ]; then for k in $KEEP; do if [ -f "$k" ] && [ -z "$(git ls-files -- "$k")" ]; then keep_changed=true; fi; done; fi
    if $still_here || $keep_changed; then
      if update_repo && $still_here; then echo "This repo no longer holds the $job files."; fi
    fi
    exit 0
    ;;

  *) echo "Usage: $0 get|put espn|tsdb"; exit 1 ;;
esac
