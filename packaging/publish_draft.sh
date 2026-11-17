#!/bin/sh
set -eu
: "${RELEASE_TAG:?RELEASE_TAG is required}"
: "${GH_REPO:?GH_REPO is required}"
notes="$(dirname "$0")/../docs/release-notes.md"
for artifact in dist/LibreFren-*.AppImage dist/LibreFren-*.AppImage.sha256; do
    test -f "$artifact"
done

if draft=$(gh release view "$RELEASE_TAG" --json isDraft --jq '.isDraft'); then
    if [ "$draft" != true ]; then
        printf '%s\n' 'Refusing to overwrite assets on a published release.' >&2
        exit 1
    fi
    gh release upload "$RELEASE_TAG" dist/LibreFren-*.AppImage dist/LibreFren-*.AppImage.sha256 --clobber
    gh release edit "$RELEASE_TAG" --tag "$RELEASE_TAG" --verify-tag --notes-file "$notes"
else
    gh release create "$RELEASE_TAG" dist/LibreFren-*.AppImage dist/LibreFren-*.AppImage.sha256 \
        --draft --prerelease --verify-tag --title "LibreFren $RELEASE_TAG" --notes-file "$notes"
fi
