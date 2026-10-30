# LineGuard security audits, October 2026 (v0.2.0 → v0.3.0)

**Scope:** the LineGuard server (`lineguard/`), the dashboard, the phone app (`app/`) with its Android and iOS projects, the VPS deployment (`deploy/vps/`) and the CI workflows.

**Method:**
- An independent review that read the code and attacked three live test servers: laptop mode, laptop with phone sharing, and hosted.
- Dependency scans: `pip-audit` and `npm audit`.
- Static analysis: `bandit`.
- End-to-end checks in a browser after the fixes.

Regression tests for the fixes are in `tests/test_lineguard.py` (`test_security_guards`, `test_hosted_password_rules`, plus additions to the pairing test).

## Findings and fixes

| # | Severity | Finding | Fix in 0.3.0 |
| --- | --- | --- | --- |
| 1 | High | **DNS rebinding.** A web page could re-point its own name at 127.0.0.1 and get full dashboard rights on the laptop. That included reading fault locations, pairing a phone for itself, and queuing any local folder. | The server answers only to IP addresses, `localhost` and configured names (`allowed_hosts`, `public_url`); others get 421. Browser requests from another origin are refused. |
| 2 | High | **Cross-site requests (CSRF).** Any website open in the same browser could upload flights, replace the tower register or start jobs. | Every dashboard request that changes something must carry an `X-LineGuard` header, which other sites can't send, and must not be cross-site. An empty import path is refused. |
| 3 | High | **Image parsing.** Pillow opened uploads in any format, including EPS, which runs Ghostscript. The installed Pillow 12.3 had published advisories. | Images are opened as JPEG/PNG only. Pillow 13.0.0 or later is required. `.npy` headers are checked before loading (2-D, at most 50 MP, numeric, no pickles). |
| 4 | High | **Stored XSS in the phone app.** Tower and line names from OpenStreetMap or imported files were shown in map tooltips as HTML. Script could have read the stored pairing tokens. | Tooltips use plain text. Every server value is validated and converted to plain values in the app. Tower and line names lose `<`, `>` and control characters on the server. The built app has a strict CSP with no network access from the web view. |
| 5 | Medium | **Pairing denial of service.** Each wrong code slept for one second, so a few requests a second blocked the server. | No sleep. Wrong codes are limited per address (5 per 10 minutes, then 429). |
| 6 | Medium | **Slow KML parsing.** A crafted 176 KB file froze the server for 12 s. | KML is read in a single forward pass. Tower files are capped at 20 MB. |
| 7 | Medium | **Hosted pairing over http.** Behind the proxy, the QR advertised `http://`, so codes and tokens could cross the internet unencrypted. | New `LINEGUARD_PUBLIC_URL` (must be https) is used for pairing links. The app refuses plain http except for IP addresses and `.local` names, and treats a redirect as an error. |
| 8 | Medium | **Committed test signing key.** Anyone could sign an "update" to the test APK and take over its stored tokens. | The key is removed from the repository. Test and Play upload keys are GitHub secrets (`app/scripts/make-test-key.sh`, `make-upload-key.sh`). The public repository starts from a clean history without it, and the old key is retired: phones with a test build signed by it (certificate SHA-256 starting `67:44:12:6F`) should uninstall it once. |
| 9 | Medium | **Pairing from links.** A `lineguard://` link or QR could pair the phone to an attacker's server in one tap, with the target hidden. | A link or QR only fills in the form and shows "Check this is your LineGuard: name at host". The address shown is the one used. |
| 10 | Medium | **Login brute force (hosted).** There was no limit on password attempts, and the example password was accepted. | 10 failed logins per address per 10 minutes, then 429. LineGuard refuses to start with a password under 12 characters or the example one. |
| 11 | Low | **Disk exhaustion.** Zip expansion was allowed up to 8 GB and free space wasn't checked (the VPS shares its disk). | Uploads are refused when less than 2 GB would remain free, checked before and during unzipping. |
| 12 | Low | **CSV formula injection** in exports. | Cells starting with `= + - @` or a tab are prefixed with `'`. |
| 13 | Low | **Android backup.** Tokens went into Google backup and device transfer. | `allowBackup="false"` plus data-extraction rules that exclude everything. |
| 14 | Low | **Broad CORS.** Any `localhost:*` page could read the API. | Only the app's own origins are allowed, plus `LINEGUARD_DEV_ORIGINS` for development. |
| 15 | Low | **No security headers;** the dashboard could be framed. | CSP, `X-Frame-Options: DENY`, `nosniff` and `Referrer-Policy` are added. The report page's inline script was moved to a file. |
| 16 | Low | **Hotspot updates.** Wrong field types caused 500 errors, and a future `changed_at` let one phone lock out others. | Fields are type-checked (400 on error), and future times are clamped to now. |
| 17 | Info | **iOS ATS and the CI action.** `NSAllowsArbitraryLoads` was on, and the Play upload action wasn't pinned. | ATS is now local-networking only. The action is pinned to a commit. |

## Checked and found sound

- SQL queries are fully parameterised.
- Zip entries are reduced to safe base names, so there is no zip slip.
- `/crops` and `/tiles` resist path traversal.
- Subprocess calls use argument lists, never a shell.
- Overpass and tile URLs come from configuration only, not from requests.
- Pairing codes use `secrets`, are single use and expire after 10 minutes. Tokens are 256-bit and stored hashed.
- Phones can't reach dashboard-only routes.
- Hosted mode requires a password and doesn't trust loopback.
- The Docker image runs as non-root and publishes no ports.
- `npm audit` reports no known vulnerabilities.

## Left as known limitations

- **Laptop link without TLS.** The laptop in the vehicle serves plain HTTP over its own Wi-Fi, so anyone who knows the Wi-Fi password can watch the traffic. `lineguard hotspot` now makes a random 14-character Wi-Fi password. A later version could add TLS with the certificate fingerprint carried in the pairing QR.
- **Token storage on the phone.** Tokens are kept in the app's own storage, not the Android Keystore or iOS Keychain. Backup is off, and tokens can be revoked from the dashboard at any time.
- **No token expiry.** Paired phones stay paired until unpaired. The dashboard shows each phone's last-seen time.
- **Custom URL scheme.** Another app could register the `lineguard://` scheme. With confirmation before pairing, the worst case is a pre-filled form the user can see. App Links / Universal Links would remove this.


---

# Round two: penetration test before going public

**Date:** 31 October 2026.

**What was tested:** two independent testers.
- One attacked live servers in laptop, shared-laptop and hosted modes. It tried to bypass every round-one fix and fuzzed every file reader.
- The other covered the git history, the build pipelines, dependencies, the phone app, the deployment files and licensing.

**Result:** the round-one fixes held under attack. Nothing allowed logging in without credentials, running code, reading files, SQL injection or script injection. What remained was mostly denial of service, release hygiene and store compliance.

Regression tests are in `test_pentest_round_two`.

## Server

| Severity | Finding | Fix |
| --- | --- | --- |
| High | Behind Caddy, every client shared the proxy's address. Ten wrong passwords from anyone therefore locked **everyone** out. | New `LINEGUARD_BEHIND_PROXY`: waitress takes the client's address from the last `X-Forwarded-For` entry (the one Caddy adds). Limits now apply per client. It requires a password and a proxy-only deployment. Verified live: the attacker gets 429, the real user gets 200. |
| Medium | Unauthenticated 4 GB request bodies were buffered to disk before the login check, on a disk shared with other apps. | Caddy checks the login (`forward_auth` to `/api/authcheck`) before accepting a large body on `/api/upload`; everything else is limited to 25 MB. On a laptop, request bodies are limited to 64 MB. Temporary files go to the data volume, where the free-space checks apply. |
| Medium | Connection flooding (slowloris): 100 half-open connections blocked new clients for up to 30 minutes. | Idle timeout cut to 60 s (a slow upload still counts as activity), 200 connections, 8 worker threads. Re-tested: 150 held connections no longer block a new client. |
| Medium | Pairing code voided for everyone after 8 wrong guesses from any mix of addresses. | Per-address limits do the work. The per-code cap is raised to 30 guesses, a 0.003% chance of guessing right. |
| Low | A zip with tens of thousands of tiny entries could exhaust inodes. | At most 20,000 entries per zip. |
| Low | Malformed GeoJSON caused 500 errors and one leaked a Python message. Malformed OpenStreetMap replies could raise. | Tower files fail with a plain message. Bad OpenStreetMap elements are skipped. |
| Low | Hosted mode without a public URL silently turned off the host-name check. | Hosted mode refuses to start without `LINEGUARD_PUBLIC_URL`. |
| Info | Paired phones could trigger OpenStreetMap fetches. Login timing differed with the username. CSV mangled negative coordinates. The dashboard tooltip didn't escape the voltage. | Fetches are dashboard-only. Both credentials are always compared. Plain numbers are no longer prefixed. The voltage is escaped. |

## App, pipeline and repository

| Severity | Finding | Fix |
| --- | --- | --- |
| High | Test signing key and its password were in git history. | Publish a clean history to a fresh repository. Retire the key. See finding 8 above. |
| Medium | The Android build job had write access to the repository while running npm and Gradle code. Actions were pinned by tag. Store secrets were repository-wide. | Read-only token by default, with a separate publish job that runs no third-party code. Checkouts don't keep credentials. `npm ci --ignore-scripts`. Every action is pinned to a commit. Store jobs run in a protected `store` environment. Artifacts are kept for 3 days. Dependabot is on. |
| Medium | A pairing link could carry hidden extra addresses, including internet ones, that the app might pair with or later send its token to. | Only the address shown is used, plus other local-network addresses for a laptop, all listed in the check. Plain `http` is accepted only for private, link-local and `.local` addresses. Map tile addresses from a server must be https. |
| Medium | The deployment guide described the other applications on the shared server. | `deploy/vps` is now generic. The container is read-only, drops all capabilities, can't gain privileges, and has PID and log limits. |
| Medium | iOS privacy manifest missing; Google ML Kit's diagnostics weren't disclosed; ML Kit and Play services are proprietary. | `PrivacyInfo.xcprivacy` added. The privacy policy and store answers now cover ML Kit. NOTICE adds a section 7 permission for the Google libraries and lists components accurately. |
| Low | Third-party licence texts weren't shipped in the app. The FileProvider was unused and too broad. The CSP comment overstated its protection. Dev tools pulled vulnerable packages. | The app has Settings → Open-source licences, generated at build time. The provider is removed and the comment corrected. `@capacitor/assets` is upgraded to 4, leaving 4 moderate advisories in dev-only tools. Production has none. |

## Still open (by design or for later)

- **Laptop link.** The vehicle Wi-Fi link is plain HTTP; anyone with the Wi-Fi password can listen. TLS with the certificate pinned in the pairing QR is planned.
- **Token storage.** On iOS, tokens live in web-view storage and are included in device backups. Moving them to the Keychain and Android Keystore is planned.
- **Proprietary scanner and location.** The QR scanner (ML Kit) and Android location (Play services) are proprietary. Replacing them with free alternatives would remove the telemetry and allow F-Droid distribution.
- **Build pinning.** `Podfile.lock` (needs a Mac), the Gradle wrapper checksum, and a digest-pinned Docker base image are still to come.
