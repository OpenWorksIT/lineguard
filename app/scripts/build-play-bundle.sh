#!/usr/bin/env bash
# Builds the signed Google Play bundle (.aab) on your own Linux computer, no GitHub Actions needed.
# Needs: Node 22, JDK 21, the Android SDK (platform 36, build-tools 36) with ANDROID_HOME set,
# and the upload key from make-upload-key.sh in ~/lineguard-upload-key/.
# Usage: app/scripts/build-play-bundle.sh [version-code]   (the version code must go up with every upload)
set -euo pipefail
cd "$(dirname "$0")/.."
KEYDIR="${LINEGUARD_KEYDIR:-$HOME/lineguard-upload-key}"
[ -f "$KEYDIR/upload.keystore" ] || { echo "No upload key in $KEYDIR. Run app/scripts/make-upload-key.sh first."; exit 1; }
[ -n "${ANDROID_HOME:-}" ] || { echo "Set ANDROID_HOME to your Android SDK folder."; exit 1; }
CODE="${1:-$(date -u +%y%m%d%H)}"
npm ci
npm run build
npx cap sync android
export LINEGUARD_KEYSTORE="$KEYDIR/upload.keystore"
export LINEGUARD_KEYSTORE_PASSWORD="$(cat "$KEYDIR/password.txt")"
export LINEGUARD_KEY_PASSWORD="$LINEGUARD_KEYSTORE_PASSWORD"
export LINEGUARD_KEY_ALIAS=upload
export LINEGUARD_VERSION_CODE="$CODE"
(cd android && ./gradlew --no-daemon bundleRelease)
VERSION=$(node -p "require('./package.json').version")
mkdir -p out
cp android/app/build/outputs/bundle/release/app-release.aab "out/LineGuard-${VERSION}-${CODE}.aab"
echo
echo "Done: app/out/LineGuard-${VERSION}-${CODE}.aab (version ${VERSION}, code ${CODE})"
echo "Upload it in Play Console > Test and release > Internal testing > Create new release."
