# Publishing the LineGuard app

This folder holds everything needed to put the app in **Google Play** and the **Apple App Store**: listing text, screenshots, graphics, privacy answers, reviewer notes, and the order of steps.

App ID on both stores: `za.co.openworks.lineguard`.
Privacy policy: <https://lineguard.openworks.co.za/privacy>. It is served by the LineGuard server, from `lineguard/templates/privacy.html`.

## 1. Accounts (one-off)

| | Google Play Console | Apple Developer Program |
| --- | --- | --- |
| Account type | **Organisation** (OpenWorks IT (Pty) Ltd) | **Organisation** |
| Needs | D-U-N-S number for the company, ID verification, US$25 once | D-U-N-S number, US$99 a year |
| Why organisation | New *personal* Play accounts must run a closed test with 12 testers for 14 days before going public. Organisation accounts are exempt. | The seller name shown in the store is the company, not a person. |

A D-U-N-S number is free from Dun & Bradstreet. It can take a few weeks, so request it first.

## 2. Signing keys (one-off, on your own computer)

Run these from the repository folder. Each needs a JDK (`keytool`) and `gh` logged in to GitHub.

```bash
app/scripts/make-test-key.sh     # key for the app-latest test APKs (so test builds install over each other)
app/scripts/make-upload-key.sh   # Google Play upload key; keeps a copy in ~/lineguard-upload-key/ — back it up
```

No key is kept in the repository. Until `make-test-key.sh` has run, test APKs are signed with a one-off key, so each one must be uninstalled before the next is installed.

For iOS, add five secrets to the `store` environment:

- `APPLE_TEAM_ID`, `ASC_KEY_ID` and `ASC_ISSUER_ID`, from an **App Store Connect API key** (Users and Access → Integrations → Team Keys, role Admin).
- `ASC_KEY_P8_B64`: the key file, encoded with `base64 -w0 AuthKey_XXXX.p8`.
- `IOS_CERT_KEY`: the RSA private key of the App Store distribution certificate, as PEM text. Use the same key as another app on the team to share its certificate, or make a new one with `openssl genrsa -out ios_cert_key.pem 2048`.

The build fetches, or creates, the distribution certificate and App Store profile through the API. No registered iPhone is needed.

## 3. Build

On GitHub, go to **Actions** and run:

- **Android store build** (`store-android.yml`). This produces `LineGuard-<version>-<code>.aab`, which you download from the run's artifacts.
  Or build it on your own Linux computer with no Actions minutes used: `app/scripts/build-play-bundle.sh`. It writes `app/out/LineGuard-<version>-<code>.aab`. Both use a date-based version code, so builds from either place stay in order.
- **iOS store build** (`store-ios.yml`). This archives, signs and uploads straight to App Store Connect. The build shows up under TestFlight after Apple has processed it (10–30 minutes).

## 4. Google Play steps

1. In Play Console, create the app: name **LineGuard**, default language English (United Kingdom), app (not game), free.
2. Under **Test and release → Internal testing**, create a release and upload the `.aab` by hand. Google requires the first upload to be done manually. Accept **Play App Signing**.
3. Fill in **App content**, using the answers below: privacy policy, app access, ads, content rating, target audience, data safety, government app (no), financial features (none), health (none).
4. Fill in **Store listing**, using the text and images below.
5. Add yourself and the client's technicians as internal testers. Check the app, then promote the release to **Production** and send it for review.
6. Optional, for later releases: create a Google Cloud service account, give it release rights in Play Console (Users and permissions), and save its JSON key as the `PLAY_SERVICE_ACCOUNT_JSON` secret. The Android store build then uploads by itself, as a draft on the track you choose.

## 5. Apple steps

1. In App Store Connect, go to **Apps → +**: iOS, name **LineGuard**, primary language English (U.K.), bundle ID `za.co.openworks.lineguard` (registered automatically by the first build), SKU `lineguard`.
2. Run the iOS store build. In **TestFlight**, add internal testers and check the app on an iPhone.
3. Under **App Information**, set category **Business** (secondary **Navigation**) and content rights (no third-party content). Age rating: answer *None* to everything, which gives **4+**.
4. Fill in **App Privacy**, using the answers below. Set the privacy policy URL as above.
5. On the version page, add the screenshots, text, review notes and demo instructions below. Pick the TestFlight build, then **Add for Review** → **Submit**.

The app is iPhone-only (the iPad layout isn't designed yet), so only iPhone screenshots are needed.

---

## Listing text

**App name** (30 max): `LineGuard`

**Google Play short description** (80 max):
`Drive straight to every hotspot your drone found on the powerlines. Offline.`

**Apple subtitle** (30 max): `Drive to powerline hotspots`

**Apple promotional text** (170 max):
`Turn a thermal drone survey into a drive list. LineGuard guides your team to each hot joint and clamp on the line, with voice prompts, even with no signal.`

**Apple keywords** (100 max):
`powerline,thermal,hotspot,inspection,drone,33kV,substation,wind farm,maintenance,infrared,O&M`

**Description** (both stores):

```
LineGuard is the field app for LineGuard, the software that turns radiometric thermal photos from your own DJI drone into a located, graded list of hotspots on overhead powerlines.

Pair the app with the LineGuard laptop in your vehicle or with your online LineGuard server, open a flight, and drive. LineGuard points the way to each fault in turn, tells you how far it is, and speaks the distance as you get closer. When you arrive, mark it repaired or not a fault and move on to the next one.

BUILT FOR REMOTE SITES
• Works with no signal: once a flight is open, the hotspots, close-up photos and nearby towers are kept on the phone
• Connects straight to the LineGuard laptop over its own Wi-Fi, with no internet or router needed
• Changes made out of range are sent automatically when you're back in range

FIND THE FAULT FAST
• Each hotspot shows its temperature rise over the other phases, its severity (major, probable, possible), the nearest tower number and a thermal close-up
• A big arrow and distance for a phone in a vehicle holder, in portrait or landscape
• Spoken prompts at 2 km, 1 km, 500 m, 200 m, 100 m and on arrival
• One tap hands the location to Google Maps, Waze, Apple Maps or an offline maps app for road directions
• Visit the closest fault next, or the major faults first

PRIVATE BY DESIGN
• Your location stays on your phone and is only used to guide you
• Flights and notes go only to your organisation's own LineGuard server
• No accounts, no ads, no tracking

Try it now: tap "Try the demo" to explore sample hotspots on a simulated 33 kV collector line.

LineGuard is made in South Africa by OpenWorks IT. To use it with your own drone surveys, you need the LineGuard software on a laptop or server: contact info@openworks.co.za.
```

**Category:** Business (Play and Apple). **Contact email:** info@openworks.co.za. **Website:** https://openworks.co.za

## Graphics

| File | For |
| --- | --- |
| `graphics/play-icon-512.png` | Play app icon (512 × 512) |
| `graphics/play-feature-graphic-1024x500.png` | Play feature graphic |
| `graphics/appstore-icon-1024.png` | Apple icon; it's already in the build, kept here for reference |
| `screenshots/android-phone-*.png` | Play phone screenshots (1080 × 1920), in order |
| `screenshots/iphone-6.9-*.png` | Apple 6.9" iPhone screenshots (1320 × 2868), in order |

The screenshots are taken from the built-in demo. Their map background is blank because the machine that made them had no access to OpenStreetMap. Before submitting, consider swapping `*-1-map.png` for a screenshot from a real phone, where the map tiles show.

To recreate them, run `npm run build && npx vite preview --port 5174`, then `node scripts/storeshots.cjs` (needs Playwright with Chromium).

---

## App access / reviewer notes

Use this for Play's **App access** ("All or some functionality is restricted") and Apple's **App Review Information → Notes**.

```
LineGuard is a work tool for powerline maintenance teams. It pairs with the organisation's own LineGuard laptop (over the laptop's Wi-Fi) or LineGuard server, which reviewers won't have.

To review every feature without one, tap "Try the demo" on the first screen. The demo contains sample hotspots on a simulated 33 kV line in the Karoo, South Africa. From there you can open the flight (map and list), open a hotspot (thermal close-up, tower, status buttons), and tap "Drive to ... open hotspots" for the guidance screen with spoken prompts. Distances will be large because the sample line is in South Africa.

Permissions:
- Location (while using): to show the distance and direction to each hotspot. It is never sent off the phone.
- Camera (iOS only): to scan the pairing QR code on the LineGuard dashboard.
- Local network (iOS): to reach the LineGuard laptop over the vehicle's Wi-Fi.
- Motion (iOS): the compass, to point the arrow.

There are no user accounts. A phone is paired with a one-time code from the organisation's dashboard and can be unpaired there.
```

No sign-in details are needed. If a reviewer asks to see pairing, show a code on the hosted test server and reply with it during the review window (codes last 10 minutes).

## Google Play: App content answers

- **Ads:** No.
- **Content rating (IARC questionnaire):** Category *Utility, Productivity, Communication or Other*. Answer No to violence, sexuality, language, controlled substances, gambling and user-to-user communication. Answer No to sharing location with other users: location is only shown to the user. Expected result: Everyone / PEGI 3.
- **Target audience:** 18 and over. It's a work tool; this keeps it out of the Families programme.
- **News app:** No. **COVID-19 app:** No. **Government app:** No.
- **Data safety:**
  - *Does your app collect or share any of the required user data types?* **Yes.**
  - *Is all of the user data collected by your app encrypted in transit?* **No.** Online servers use HTTPS, but the laptop in the vehicle is reached over its own WPA2-protected Wi-Fi without HTTPS.
  - *Do you provide a way for users to request that their data is deleted?* **Yes** (Forget in the app, the organisation's dashboard, or info@openworks.co.za).
  - Data types collected:
    - **App activity → Other user-generated content.** Hotspot status changes and notes. Collected, not shared. Not processed ephemerally. Optional. Purpose: App functionality.
    - **App info and performance → Diagnostics.** Sent to Google by the ML Kit QR scanner: device model, OS and app version, scan latency, error codes ([Google's ML Kit data disclosure](https://developers.google.com/ml-kit/android-data-disclosure)). Collected, not shared, encrypted in transit, not ephemeral, required (whenever the scanner is used). Purpose: Analytics (Google's diagnostics and usage analytics for ML Kit).
    - **Device or other IDs.** ML Kit uses a per-installation identifier for those diagnostics. Collected, not shared, required. Purpose: Analytics.
    - The phone name typed at pairing is user-generated content, covered above.
  - Not collected: location (used on the phone only), personal info, financial info, health, messages, photos (thermal close-ups are downloaded, not uploaded), audio, files, calendar, contacts, web history.

## Apple: App Privacy answers

- **Do you or your third-party partners collect data from this app?** Yes.
- **User Content → Other User Content** (hotspot notes, status changes and the phone's name). Purpose: **App Functionality**. Linked to the user's identity: **Yes**, because a change is recorded with the name of the phone that made it. Used for tracking: **No**.
- **Diagnostics → Performance Data** and **Other Diagnostic Data**, collected by Google's ML Kit (the QR scanner): device model, OS version, scan latency and error codes. Purpose: **Analytics** (for Google, about ML Kit). Linked to the user: **No**. Used for tracking: **No**. Check these answers against the privacy report Xcode generates for the archive (Organizer → Generate Privacy Report), which includes ML Kit's own privacy manifests.
- Everything else: not collected. Location is used on the device only, so under Apple's definition it is not "collected".

## Before each release

- Bump `version` in `app/package.json`. The Android version name and the iOS version both come from it.
- Run the server tests (`pytest`) and try the demo in a browser (`npm run dev`).
- Check that the privacy policy still matches what the app does.
- Tag the release and push the tag: `git tag v0.3.0 && git push origin v0.3.0`. This runs both store builds: the iPhone app goes to TestFlight, and the Android bundle goes to Play's internal track (once `PLAY_SERVICE_ACCOUNT_JSON` is set), or is left as a download on the run.
- In App Store Connect and Play Console, pick the new build and send it for review.
