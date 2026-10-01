#!/bin/bash
# The P13 regression of record, run OUTSIDE the tracked worktree.
#
#   scripts/guided_workspace/final_regression.sh <SHA> [WORKDIR] [OUTDIR]
#
# A fresh local clone at exactly <SHA> is made in WORKDIR (default
# /home/user/gw_final_<sha12>); the untracked runtime inputs (candidate
# interpreter, published lakes, emulator pickles, node_modules) are linked in
# read-only fashion; every suite then runs in the clone, so nothing any suite
# writes -- logs, screenshots, evidence JSON, .next -- can touch the tracked
# worktree. Results go to OUTDIR (default /home/user/gw_final_out_<sha12>) and
# are copied into docs/ only after every suite has finished.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SHA="$(git -C "$REPO" rev-parse "${1:?usage: final_regression.sh <SHA> [WORKDIR] [OUTDIR]}")"
SHORT="${SHA:0:12}"
WORK="${2:-/home/user/gw_final_$SHORT}"
OUT="${3:-/home/user/gw_final_out_$SHORT}"
[ -e "$WORK" ] && { echo "refusing: $WORK exists"; exit 2; }
[ -n "$(git -C "$REPO" status --porcelain)" ] && { echo "refusing: the tracked worktree is not clean"; exit 2; }

git clone --quiet --no-local "$REPO" "$WORK"
git -C "$WORK" checkout --quiet --detach "$SHA"
[ "$(git -C "$WORK" rev-parse HEAD)" = "$SHA" ] || { echo "clone is not at $SHA"; exit 2; }

ln -s "$REPO/.venv-whatif" "$WORK/.venv-whatif"
mkdir -p "$WORK/data"
ln -s "$REPO/data/cockpit_v4" "$WORK/data/cockpit_v4"
ln -s "$REPO/data/cockpit_v4_lake" "$WORK/data/cockpit_v4_lake"
for pkl in "$REPO"/artifacts/whatif/*/*.pkl; do
  rel="${pkl#$REPO/}"; ln -s "$pkl" "$WORK/$rel"
done
cp -al "$REPO/frontend/node_modules" "$WORK/frontend/node_modules"
# The links are runtime inputs, not edits: keep them out of `git status` so
# the runner's frozen-tree check sees exactly the committed candidate.
printf '%s\n' /.venv-whatif /data/cockpit_v4 /data/cockpit_v4_lake \
  '/artifacts/whatif/*/*.pkl' >> "$WORK/.git/info/exclude"
[ -z "$(git -C "$WORK" status --porcelain)" ] || { git -C "$WORK" status --porcelain; echo "clone is not clean"; exit 2; }

echo "clone   $WORK @ $SHA"
echo "results $OUT"
cd "$WORK"
set +e
/home/user/.venv312/bin/python scripts/guided_workspace/regression_of_record.py --out "$OUT"
rc=$?
set -e
# After every suite has finished: copy what the suites wrote inside the
# clone (evidence JSON, screenshots, logs), path for path, next to the
# results. The tracked worktree is not touched.
mkdir -p "$OUT/suite_outputs"
git -C "$WORK" status --porcelain --untracked-files=all \
  | sed -E 's/^.{3}//; s/.* -> //' \
  | grep -vE '^(\.venv-whatif|data/cockpit_v4|frontend/node_modules|artifacts/whatif/.*\.pkl$)' \
  | while read -r rel; do
      [ -f "$WORK/$rel" ] || continue
      mkdir -p "$OUT/suite_outputs/$(dirname "$rel")"
      cp -p "$WORK/$rel" "$OUT/suite_outputs/$rel"
    done
git -C "$WORK" status --porcelain --untracked-files=all > "$OUT/suite_outputs.status"
git -C "$WORK" rev-parse HEAD > "$OUT/clone_head"
echo "regression exit $rc; suite outputs copied to $OUT/suite_outputs"
exit $rc
