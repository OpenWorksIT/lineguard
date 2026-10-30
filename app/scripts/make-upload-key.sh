#!/usr/bin/env bash
# Creates the Google Play *upload* key and saves it as secrets of the "store" environment, used by store-android.yml.
# Create that environment first: repository Settings > Environments > New environment "store".
# Run once on your own computer, from the repository folder. Needs keytool (any JDK) and gh (logged in).
# Google Play holds the real app signing key (Play App Signing); this key only proves uploads come from you.
# Keep the copy this script leaves in ~/lineguard-upload-key/ somewhere safe (e.g. your password manager):
# if it's lost, Google can reset it, but that takes a support request.
set -euo pipefail
for tool in keytool openssl gh; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Install it first:"; echo "  Mint/Ubuntu: sudo apt install openjdk-21-jdk-headless openssl gh"; echo "  Fedora/Nobara: sudo dnf install java-21-openjdk-headless openssl gh"; exit 1; }
done
gh auth status >/dev/null 2>&1 || { echo "Log in to GitHub first: gh auth login"; exit 1; }
REPO="${1:-OpenWorksIT/lineguard}"
OUT="$HOME/lineguard-upload-key"
mkdir -p "$OUT"
chmod 700 "$OUT"
PW=$(openssl rand -hex 24)
keytool -genkeypair -keystore "$OUT/upload.keystore" -storetype PKCS12 -alias upload \
  -keyalg RSA -keysize 4096 -validity 10000 -storepass "$PW" -keypass "$PW" \
  -dname "CN=OpenWorks IT, O=OpenWorks IT (Pty) Ltd, C=ZA"
printf %s "$PW" > "$OUT/password.txt"
chmod 600 "$OUT"/*
base64 -w0 "$OUT/upload.keystore" | gh secret set LINEGUARD_UPLOAD_KEYSTORE_B64 --env store -R "$REPO"
printf %s "$PW" | gh secret set LINEGUARD_KEYSTORE_PASSWORD --env store -R "$REPO"
printf %s "$PW" | gh secret set LINEGUARD_KEY_PASSWORD --env store -R "$REPO"
printf upload | gh secret set LINEGUARD_KEY_ALIAS --env store -R "$REPO"
echo "Upload key saved as secrets of the store environment in $REPO, with a copy in $OUT (back it up, then you may delete it)."
