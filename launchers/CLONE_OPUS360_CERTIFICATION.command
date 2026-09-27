#!/bin/bash
# Create the independent certification clone on this Mac (never a worktree of the
# presentation folder), pinned to the certification branch built on the frozen tag.
set -e
DEST="${OPUS360_CLONE_DIR:-$HOME/Desktop/IPM_V2-AdvancedCockpit-Opus360}"
if [ -d "$DEST/.git" ]; then echo "Already exists: $DEST"; else
  git clone --branch claude/opus360-architecture-certification https://github.com/tuhinchatterjee/IPM_V2 "$DEST"
fi
cd "$DEST"
git fetch --tags origin
TAG_COMMIT=$(git rev-parse "cockpit-round-h-live-pass-2026-09-23^{commit}")
if [ "$TAG_COMMIT" != "245c50e45786c6e0c866b281f9dd74da17d160b5" ]; then
  echo "STOP: the frozen tag resolves to $TAG_COMMIT, not 245c50e4..."; exit 1; fi
git merge-base --is-ancestor 245c50e45786c6e0c866b281f9dd74da17d160b5 HEAD
echo "Clone ready at $DEST (branch $(git branch --show-current), HEAD $(git rev-parse --short HEAD))."
echo "Optional: export OPUS360_LAKE_SOURCE=/path/to/presentation/clone/data  (copies the approved release bytes)"
echo "Next: $DEST/launchers/SETUP_OPUS360.command"
[ -t 0 ] && read -r -p "Press return to close this window. "
