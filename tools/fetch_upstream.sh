#!/bin/sh
# Fetch the upstream OutGuess 0.4 sources that the oracle build and the
# fixture generators need.
#
#   tools/fetch_upstream.sh [target-dir]
#
# The default target is ../_upstream, which is what tools/build_reference.sh
# looks for.  The tree is pinned to the 0.4 release commit so the reference
# binaries -- and therefore every bit-exactness claim in validation/NOTES.md --
# stay reproducible.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
DEST=${1:-$ROOT/_upstream}

REPO=${OUTGUESS_REPO:-https://github.com/resurrecting-open-source-projects/outguess.git}
# "Prepare to release version 0.4"
COMMIT=${OUTGUESS_COMMIT:-24810e1}
# Kept as a fallback in case the tag is what is available instead.
TAG=${OUTGUESS_TAG:-v0.4}

if [ -d "$DEST/src" ]; then
	echo "upstream already present: $DEST"
	echo "(remove it first if you want a fresh checkout)"
	exit 0
fi

if ! command -v git >/dev/null 2>&1; then
	echo "git is required to fetch $REPO" >&2
	exit 1
fi

echo "fetching $REPO into $DEST"
rm -rf "$DEST"
git clone --quiet "$REPO" "$DEST"
if git -C "$DEST" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
	git -C "$DEST" checkout --quiet "$COMMIT"
elif git -C "$DEST" rev-parse --verify --quiet "$TAG" >/dev/null; then
	echo "commit $COMMIT not found, falling back to tag $TAG" >&2
	git -C "$DEST" checkout --quiet "$TAG"
else
	echo "warning: neither $COMMIT nor $TAG found; staying on the default branch" >&2
fi

# The tree carries a .git directory so that the checkout can be updated; the
# build scripts never look inside it, and .gitignore keeps it out of the repo.
echo "upstream ready: $(git -C "$DEST" rev-parse --short HEAD)"
echo "now run: tools/build_reference.sh"
