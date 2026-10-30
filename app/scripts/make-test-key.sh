#!/usr/bin/env bash
# Creates the signing key for LineGuard *test* builds (the app-latest APKs) and saves it as GitHub
# secrets, so every test build is signed with the same key and installs over the previous one.
# Run once on your own computer, from the repository folder. Needs keytool (any JDK) and gh (logged in).
# This key never goes into the repository. It's separate from the Google Play upload key.
set -euo pipefail
for tool in keytool openssl gh; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Install it first:"; echo "  Mint/Ubuntu: sudo apt install openjdk-21-jdk-headless openssl gh"; echo "  Fedora/Nobara: sudo dnf install java-21-openjdk-headless openssl gh"; exit 1; }
done
gh auth status >/dev/null 2>&1 || { echo "Log in to GitHub first: gh auth login"; exit 1; }
REPO="${1:-OpenWorksIT/lineguard}"
DIR=$(mktemp -d)
trap 'rm -rf "$DIR"' EXIT
PW=$(openssl rand -hex 24)
keytool -genkeypair -keystore "$DIR/test.keystore" -storetype PKCS12 -alias lineguard-test \
  -keyalg RSA -keysize 3072 -validity 10000 -storepass "$PW" -keypass "$PW" \
  -dname "CN=LineGuard test build, O=OpenWorks IT, C=ZA" > /dev/null
base64 -w0 "$DIR/test.keystore" | gh secret set LINEGUARD_TEST_KEYSTORE_B64 -R "$REPO"
printf %s "$PW" | gh secret set LINEGUARD_TEST_KEYSTORE_PASSWORD -R "$REPO"
echo "Saved the test signing key as secrets in $REPO."
echo "Phones with an older test build: uninstall it once, then install the next build."
