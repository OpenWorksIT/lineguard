<p align="center"><img src="assets/logo.svg" alt="LineGuard: thermal imaging software for powerlines" width="420"></p>

LineGuard finds hotspots on powerlines in radiometric drone photos and gives each one coordinates a technician can drive to. It runs as a background service on a laptop, fully offline, with a dashboard in the browser.

Part of **Project Argus** by [OpenWorks IT](https://www.openworks.co.za).

## How it works

1. Fly the line with a radiometric thermal drone (built for the DJI Matrice 4T), camera pointing straight down, photos every few metres with about 80% overlap.
2. Copy the flight folder from the memory card into the inbox (`~/LineGuard/inbox`), or paste its path into the dashboard.
3. LineGuard finds the conductors in each photo and compares every phase with the other two at the same point. It keeps only the hotspots that appear in most of the overlapping photos that covered them, then places each one on the map.
4. Technicians get a map, a printable report with a QR code per fault, and KML, GPX and CSV files for navigation apps.
5. Asset teams get every flight, fault, repair and recheck as documented tables for Power BI, Databricks or Excel.

Each hotspot is graded on NETA's similar-component bands: possible (1 to 3 °C), probable (4 to 15 °C) and major (over 15 °C).

## Fault history and recurrence tracking

LineGuard keeps the full history of every fault, and checks each spot again on later flights:

- **Every change is kept, with its time.** LineGuard records when it found each hotspot, plus every status change and note from the dashboard or a phone, with who made it. A phone that was out of signal sends the time the technician made the change, not the time it reached the server.
- **One spot, one ID.** A hotspot found again on a later flight is linked to the earlier one, so a spot's whole timeline sits together: found, repaired, checked, and found again if it came back.
- **Every repair gets checked by the next flight.** When a later flight's photos cover a spot that had been marked repaired, LineGuard records whether the repair held or the fault came back. Faults that come back are flagged **Came back** on the dashboard, the printed report and the phone app.
- **Reprocessing keeps the history.** Processing a flight again, for example with new settings, keeps each hotspot's identity, status and notes. Hotspots it no longer finds are marked as gone, never silently deleted.

## Data for Power BI and Databricks

Everything LineGuard knows comes out as five documented tables: sites, flights, hotspots, hotspot events (the history) and revisits (each later flight over each spot, with its outcome). They come as Parquet and CSV, described in the open [Frictionless Data Package](https://datapackage.org) format. The format guide is [docs/data-format.md](docs/data-format.md). Every row carries a site ID and permanent IDs, so several laptops and servers can feed one lakehouse.

- **Live feed:** `https://<server>/api/data/v1/<table>.parquet` (or `.csv`). Each reporting tool gets its own read-only data key from the dashboard (**Data feed**). A key can read these tables and nothing else.
- **Folder drop for site laptops:** `lineguard export-data ~/OneDrive/LineGuard/site-a` writes the tables into a folder that syncs when there is signal. Run it from a timer to keep the folder fresh.
- **Download:** the dashboard's **Data feed → Download all data** gives everything as one zip.

Ready-made connectors are in [integrations/](integrations/):

- **Power BI:** typed queries, relationships and measures such as repair hold rate and median days to repair.
- **Databricks:** a notebook that loads one or more sites into Unity Catalog, with views for open faults, repair outcomes and KPIs.

## Install (Linux)

Python 3.11 or newer.

```bash
pip install git+https://github.com/OpenWorksIT/lineguard
lineguard install-service      # systemd user service + "LineGuard" app launcher
lineguard open                 # dashboard at http://127.0.0.1:8750/
```

If you'd rather not install the service, run `lineguard serve --open` in a terminal.

For an offline laptop, download the wheels on a connected machine and copy them across:

```bash
pip download "lineguard @ git+https://github.com/OpenWorksIT/lineguard" -d wheels/
pip install --no-index --find-links wheels/ lineguard
```

## Phone app and driving to faults

The LineGuard app ([app/](app/README.md)) runs on Android and iOS. Technicians use it to drive to each hotspot, with an arrow, the distance and spoken prompts. It works offline once a flight is open on the phone.

It connects in one of two ways:
- **To the laptop in the vehicle, over Wi-Fi.** Run `lineguard install-service --share`, and `lineguard hotspot` if there's no other Wi-Fi.
- **To a hosted LineGuard, over mobile data.**

To pair a phone, choose **Connect a phone** in the dashboard. Pairing codes last ten minutes and work once. Paired phones can be unpaired from the same panel.

Without a password, the laptop's own browser needs no login. Every other device must be a paired phone. The dashboard answers only to IP addresses and `localhost`; if you open it by another name (for example `bakkie-laptop.local`), add that name to `allowed_hosts`.

To publish the app in Google Play and the App Store, see [app/store/README.md](app/store/README.md). The latest security review and its fixes are in [docs/security-audit-2026-10.md](docs/security-audit-2026-10.md).

## Tower numbers

Each hotspot is labelled with the nearest tower, for example "Tower T44, Collector A 33 kV line". The data comes from two sources:

- **OpenStreetMap**, the data behind [openinframap.org](https://openinframap.org). When the laptop is online, power lines, towers and substations around each flight are fetched once through the Overpass API and kept with the flight.
- **Your own tower register.** Wind-farm 33 kV collector lines are rarely mapped in OpenStreetMap, so import your own list in the dashboard under **Tower list**. It takes a CSV of `ref, lat, lon[, line]`, or KML or GeoJSON points, and works offline.

Map and power data © OpenStreetMap contributors (ODbL).

## Hosting it for remote testing

`deploy/vps/` runs LineGuard as a Docker container behind an existing Caddy, with a login and browser uploads instead of the local inbox. See [deploy/vps/README.md](deploy/vps/README.md).

## Try it without a drone

```bash
lineguard demo                          # a simulated 500 m, 33 kV flight lands in the inbox
lineguard demo --scenario 33kv_hot      # the same line on a hot afternoon
```

The service picks the flight up within a few seconds. The planted faults are saved in the flight folder as `_truth.json`, so you can check what was found against what was planted.

## Real flights (DJI Matrice 4T)

**Decoding temperatures.** DJI's R-JPEG photos are decoded with `dji_irp`, part of the [DJI Thermal SDK](https://www.dji.com/downloads/softwares/dji-thermal-sdk). The SDK can't be bundled with LineGuard, so download it from DJI and point LineGuard at the tool:

```toml
# ~/.config/lineguard/config.toml   (create a template with: lineguard init-config)
dji_irp = "/opt/dji_thermal_sdk/utility/bin/linux/release_x64/dji_irp"

[detection]
standoff_m = 20.0     # distance from camera to conductors that the route is flown at
```

**Flight settings LineGuard expects:**

- Gimbal pitch -90° (straight down). Photos pitched more than 10° from straight down are skipped.
- Camera heading following the route, so the conductors run up the photo.
- Thermal photos saved as R-JPEG, by distance interval, with about 80% front overlap.
- RTK fix. On sites with no mobile signal, use a local base station such as the D-RTK 3.
- Fly when the ground is cool (morning, overcast). Sun-heated ground hides small faults on thin conductors.

Position and heading come from each photo's XMP data. Any matching wide photo (`_W.JPG`) is used for a colour close-up.

## Offline maps

Hotspot coordinates never need a network. The map background does. To have one offline, put tiles in `~/.local/share/lineguard/tiles/{z}/{x}/{y}.png` (any XYZ tile set you're licensed to use, e.g. made with QGIS's "Generate XYZ tiles") and LineGuard serves them itself.

## Settings

Everything is optional. These are the defaults:

| Setting | Default | Meaning |
| --- | --- | --- |
| `host`, `port` | `127.0.0.1`, `8750` | Dashboard address. Keep it on localhost unless the network is trusted. |
| `inbox_dir` | `~/LineGuard/inbox` | Folders copied here are processed automatically. |
| `data_dir` | `~/.local/share/lineguard` | Database, close-ups, offline tiles. |
| `dji_irp` | | Path to the DJI Thermal SDK's `dji_irp` tool. |
| `tiles_url` | OpenStreetMap | Online map tiles, used when no offline tiles exist. |
| `allowed_hosts` | | Extra names the dashboard may be opened by, comma separated. |
| `public_url` | | Hosted only (required): the https address phones and browsers use (`LINEGUARD_PUBLIC_URL`). |
| `behind_proxy` | `false` | Hosted behind Caddy: take each client's address from `X-Forwarded-For` so login limits apply per client. Only when the proxy is the sole way in. |
| `password` | | Requires a login (12 characters or more). Always set when hosted. |
| `camera_timezone` | this computer's | Time zone the drone's clock is set to, e.g. `Africa/Johannesburg`. Gives every flight a UTC time, so flights can be compared with repairs (`LINEGUARD_CAMERA_TIMEZONE`). |
| `[detection] standoff_m` | `20.0` | Camera-to-conductor distance. The laser range is used instead when it plausibly hit the line. |
| `[detection] threshold_c` | `3.0` | Minimum rise over the other phases to flag. |
| `[detection] phases` | `3` | Conductors expected side by side in each photo. |
| `[camera] diagonal_fov_deg` | `45.0` | Thermal camera field of view (Matrice 4T). |

## Other cameras

Any camera that can export per-pixel temperatures works through the generic format: one `name.npy` array (°C) and one `name.json` per photo, holding `lat`, `lon`, `yaw_deg` and optionally `pitch_deg`, `range_m` and `taken`. See `lineguard/readers/generic.py`.

## Limits of this first version

- Straight-down views only, with the phases side by side (horizontal configuration). Vertical and delta configurations need an oblique view and aren't supported yet.
- The detection is tested on simulated flights, not real ones yet. Thresholds will be tuned on the first real flights.
- The `dji_irp` command line follows the Thermal SDK's sample tool. Check it against the SDK version you install.
- The colour close-up is cut from the wide photo by field-of-view geometry, so its framing is approximate.

## Development

```bash
pip install -e ".[test]"
pytest
```

Layout: `readers/` (DJI and generic photos), `detect.py` (the method), `pipeline.py` (one flight end to end), `worker.py` (inbox watcher), `web.py` with `templates/` and `static/` (dashboard), `opendata.py` (the data format and its exports; `integrations/generate.py` regenerates the docs and Power Query files from it), `demo_scene.py` (the flight simulator used by the demo and the tests).

The dashboard uses [Leaflet](https://leafletjs.com) (BSD-2-Clause), bundled in `lineguard/static/vendor/leaflet`.

## Licence

LineGuard is free software, © 2026 OpenWorks IT (Pty) Ltd, licensed under the [GNU Affero General Public License v3.0 or later](LICENSE). You may use, study, change and share it. If you run a modified version for others over a network, you must offer them its source (set `source_url` so the dashboard and app link to it).

[NOTICE](NOTICE) lists:
- an extra permission that lets the phone app be distributed through app stores;
- the names and logos, which stay with OpenWorks IT releases;
- the DJI Thermal SDK, which isn't part of LineGuard;
- the third-party components.
