# LineGuard field app (Android and iOS)

The phone app technicians use to drive to each hotspot. It connects either to the LineGuard laptop in the vehicle over Wi-Fi or to a hosted LineGuard over mobile data. Once a flight is open on the phone, it keeps working with no signal at all.

**What it does:**

- **Pairing:** scan the QR code from the dashboard's "Connect a phone", or type the address and 6-digit code.
- **Demo:** "Try the demo" opens sample hotspots on a simulated 33 kV line, with no LineGuard needed.
- **Flights:** each flight's hotspots, close-up photos and nearby power lines and towers are saved on the phone.
- **Map and list:** shows where you are, with hotspots sorted by distance.
- **Drive mode:** a big arrow and the distance to the next hotspot, with spoken prompts at 2 km, 1 km, 500 m, 200 m and 100 m and on arrival. It also shows the tower number and a thermal close-up.
  - Mark each fault repaired or not a fault, or skip it, and the next one comes up.
  - The screen stays on, and there's a landscape layout for a phone holder.
- **Road directions:** hands the hotspot to Google Maps, Waze, Apple Maps or any maps app. Those can navigate offline if the area has been downloaded in them.
- **Offline changes:** anything marked with no connection is kept on the phone and sent when it's back in range. If someone else changed the same hotspot more recently, the newer change wins.

## Using it in the vehicle

1. On the laptop, turn on phone sharing once: `lineguard install-service --share`.
2. If the vehicle has no Wi-Fi, make the laptop the hotspot: `lineguard hotspot`. It prints the network name and password.
3. Connect the phone to that Wi-Fi. In the dashboard choose **Connect a phone**, then scan the code with the app.
4. Open a flight on the phone and choose **Drive to … open hotspots**.

GPS works with no signal. LineGuard's arrow and distance come from GPS alone. The map background only shows areas the phone or laptop has seen online, or tiles you've put on the laptop.

## Getting the app

- **Android:** every push builds a test APK, published as the [app-latest pre-release](../../releases/tag/app-latest). Open it on the phone and allow installs from that source. Test builds are signed with the key saved by `scripts/make-test-key.sh` (a GitHub secret, never in the repository), so newer ones install over older ones.
- **Google Play and App Store:** see [store/README.md](store/README.md) for keys, store builds, listing text, screenshots and privacy answers.
- **iOS:** CI builds the app for the simulator to prove it compiles. Putting it on iPhones needs an Apple Developer account (US$99 a year) and a Mac or a macOS CI runner with signing set up. The usual route is TestFlight:
  1. Create the app ID `za.co.openworks.lineguard` in App Store Connect.
  2. Open `ios/App/App.xcworkspace` in Xcode on a Mac, choose your team under Signing, then Product > Archive > Distribute > TestFlight.
  3. Or add the signing certificate and provisioning profile as CI secrets and extend `.github/workflows/app-ios.yml` with an archive and upload step (for example with fastlane).

## Developing

```bash
npm install
npm run dev             # the app in a browser at http://127.0.0.1:5173, or tap "Try the demo"
# to pair the browser with a LineGuard on this machine, start it with the dev origin allowed:
#   LINEGUARD_DEV_ORIGINS=http://127.0.0.1:5173 lineguard serve --share
npm run build && npx cap sync      # copy into the Android and iOS projects
npx cap open android    # Android Studio
```

In a browser the app runs the same code. Location comes from the browser, and requests go through normal `fetch`. The server allows the app's own origins (`capacitor://localhost`, `http(s)://localhost`) by CORS, plus any listed in `LINEGUARD_DEV_ORIGINS`.

**Security notes:**

- Everything a server sends is checked and reduced to plain values (`clean*` in `src/api.js`) before it reaches the screen.
- The built app has a Content Security Policy that gives the web view no network access of its own. Server requests go through native HTTP.
- A QR code or link only fills in the pairing form. The user sees the address and taps Pair.
- Online servers must use `https://`. Plain `http://` is accepted only for IP addresses and `.local` names on the vehicle Wi-Fi.
- Android backup and device-to-device transfer are off, so pairing tokens stay on the phone they were issued to.

On a phone, requests go through native HTTP. That's what lets it reach a laptop on plain `http://` over the vehicle Wi-Fi: Android has cleartext allowed, and iOS has local networking allowed in `Info.plist`.

Icons and splash screens come from `assets/` (`npm run assets`).

**Code layout:**

| File | What it handles |
| --- | --- |
| `src/api.js` | Pairing, connection, offline copies, change queue |
| `src/device.js` | GPS, compass, voice, keep-awake, maps hand-off |
| `src/geo.js` | Distance, bearing, visiting order |
| `src/map.js` | Leaflet map with cached tiles and OSM power lines |
| `src/main.js` | Screens |
