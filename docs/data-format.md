# LineGuard open data format 1.0

Generated from `lineguard/opendata.py`; don't edit by hand.

Every export has the same five tables, each as Parquet (typed) and CSV (UTF-8, comma separated, ISO 8601 times). `datapackage.json` describes them in the open [Frictionless Data Package](https://datapackage.org) standard.

* IDs ending in `_uid` are permanent and unique across every LineGuard installation, so exports from several sites can be stacked into one table.
* Columns ending in `_utc` are UTC. `flown_at_local` is the drone's own clock; `flown_at_utc` converts it with the `camera_timezone` setting.
* Blank means not known or not applicable.
* Text that starts with `=`, `+`, `-` or `@` gets a leading `'` in the CSV files only, so a spreadsheet doesn't run it as a formula. The Parquet files hold the text unchanged.
* The data is small (thousands of rows), so the simplest load is to replace every table on each refresh. To merge instead, use the `_uid` key of each table.

## How the tables fit together

```
sites 1──* flights 1──* hotspots 1──* hotspot_events
                          │  └─ place_uid groups sightings of one spot across flights
                          └──* revisits *──1 flights (the later flight)
```

## sites

The LineGuard server or laptop this export came from.

Key: `site_id`

| Column | Type | Meaning |
|---|---|---|
| `site_id` | text | Permanent ID of this LineGuard installation. Every other table carries it, so exports from several sites can be stacked. |
| `site_name` | text | The name this LineGuard shows on phones. |
| `lineguard_version` | text | LineGuard version that wrote the export. |
| `data_format_version` | text | Version of this data format. |
| `exported_at_utc` | date-time, UTC | When the export was made. |
| `camera_timezone` | text | Time zone used to turn the drone's clock into UTC. |

## flights

One row per processed drone flight.

Key: `flight_uid`

| Column | Type | Meaning |
|---|---|---|
| `site_id` | text | The site this flight belongs to. |
| `flight_uid` | text | Permanent ID of the flight. |
| `flight_number` | whole number | The flight's number on the dashboard (only unique within one site). |
| `flight_name` | text | Name given to the flight (usually its folder name). |
| `flown_at_local` | date-time, drone clock | When the first photo was taken, by the drone's clock. |
| `flown_at_utc` | date-time, UTC | flown_at_local converted to UTC with camera_timezone. Use this to compare flights with repairs. |
| `added_at_utc` | date-time, UTC | When the flight was added to LineGuard. |
| `processing_status` | text | queued, processing, done or failed. |
| `photos` | whole number | Thermal photos in the flight. |
| `photos_skipped` | whole number | Photos that could not be used (not looking straight down, unreadable). |
| `lines_found` | whole number | Photos in which the conductors were found. |
| `candidates_rejected` | whole number | Hot spots seen in one photo only and therefore dropped. |
| `standoff_m` | number | Distance from the camera to the conductors, in metres. |
| `centre_latitude` | number | Middle of the flight, WGS84. |
| `centre_longitude` | number | Middle of the flight, WGS84. |
| `hotspots` | whole number | Confirmed hotspots in this flight. |
| `hotspots_open` | whole number | Of those, how many are still open. |
| `major_open` | whole number | Open hotspots rated major. |

## hotspots

One row per confirmed hotspot, with its current status.

Key: `hotspot_uid`

| Column | Type | Meaning |
|---|---|---|
| `site_id` | text | The site this hotspot belongs to. |
| `hotspot_uid` | text | Permanent ID of the hotspot. Survives reprocessing the flight. |
| `label` | text | The hotspot's name on the dashboard and phones, e.g. LG-12 (only unique within one site). |
| `flight_uid` | text | The flight that found it. |
| `place_uid` | text | The same spot across all flights: every sighting of one fault position shares this ID (it is the hotspot_uid of the first sighting). |
| `previous_hotspot_uid` | text | The nearest hotspot at the same spot on an earlier flight, if there was one. |
| `sighting_number` | whole number | 1 for the first time this spot was found, 2 for the second flight that found it, and so on. |
| `is_latest_sighting` | true/false | True for the most recent sighting of this spot. Count open faults with is_open and is_latest_sighting, so a fault seen on several flights counts once. |
| `recurring` | true/false | True if this spot had been marked repaired before this flight and the fault is back. |
| `repairs_before` | whole number | How many earlier sightings of this spot had been marked repaired before this flight. |
| `latitude` | number | WGS84. |
| `longitude` | number | WGS84. |
| `temperature_rise_c` | number | How much hotter than the other phases at the same point, in °C. |
| `previous_rise_c` | number | The rise at the same spot on the earlier flight. |
| `rise_change_c` | number | temperature_rise_c minus previous_rise_c. Positive means getting hotter. |
| `severity` | text | possible (under 4 °C), probable (4 to 15 °C) or major (over 15 °C), after NETA similar-component bands. |
| `severity_rank` | whole number | 1 possible, 2 probable, 3 major. Sort and filter by this. |
| `status` | text | open, repaired or dismissed (not a fault). |
| `is_open` | true/false | True while the status is open. |
| `found_at_utc` | date-time, UTC | When LineGuard found it. |
| `flown_at_utc` | date-time, UTC | When the flight that found it was flown. |
| `status_changed_at_utc` | date-time, UTC | When the status last changed (blank while it has never changed). |
| `status_changed_by` | text | Phone or dashboard that last changed the status. |
| `repaired_at_utc` | date-time, UTC | When it was marked repaired, if its status is repaired. |
| `days_open` | number | Days from the flight to the repair, or to the export while still open. |
| `note` | text | The latest note from a technician. |
| `photos_confirming` | whole number | Photos the hotspot was seen in. |
| `photos_covering` | whole number | Photos that covered the spot. |
| `photo_name` | text | The best photo of it. |
| `tower_ref` | text | Nearest tower or pole, from the client's tower list or OpenStreetMap. |
| `tower_kind` | text | tower or pole. |
| `tower_distance_m` | number | Distance to that tower, in metres. |
| `line_name` | text | Power line name, where known. |
| `line_voltage_kv` | number | Line voltage in kV, where known. |
| `line_operator` | text | Line operator, where known. |
| `google_maps_url` | text | Link that opens the position in Google Maps. |

## hotspot_events

Every hotspot's history: found, status changes, notes, and gone after reprocessing. Rows are only ever added.

Key: `event_uid`

| Column | Type | Meaning |
|---|---|---|
| `site_id` | text | The site this event belongs to. |
| `event_uid` | text | Permanent ID of the event. |
| `hotspot_uid` | text | The hotspot it happened to. A 'gone' hotspot no longer appears in the hotspots table. |
| `event_number` | whole number | Order of events within one site. |
| `at_utc` | date-time, UTC | When it happened. Changes made on a phone without signal carry the time they were made, not the time they were sent. |
| `kind` | text | found, status, note or gone (processing the flight again no longer finds it). |
| `status` | text | The new status, for found and status events. |
| `note` | text | The note, for note and gone events. |
| `changed_by` | text | Phone or dashboard that made the change. |

## revisits

Each later flight that passed over a hotspot's spot, and what it found there.

Key: `revisit_uid`

| Column | Type | Meaning |
|---|---|---|
| `site_id` | text | The site. |
| `revisit_uid` | text | Permanent ID of this hotspot-and-flight pair (the same in every export). |
| `hotspot_uid` | text | The hotspot being checked. |
| `place_uid` | text | The spot, as in the hotspots table. |
| `revisit_flight_uid` | text | The later flight that covered the spot. |
| `hotspot_flown_at_utc` | date-time, UTC | When the hotspot was first seen. |
| `revisit_flown_at_utc` | date-time, UTC | When the later flight flew over it. |
| `days_between` | number | Days between the two flights. |
| `status_at_revisit` | text | The hotspot's status when the later flight flew: open, repaired or dismissed. |
| `repaired_at_utc` | date-time, UTC | When it was marked repaired, if that was before the later flight. |
| `days_repair_to_revisit` | number | Days from the repair to the later flight. |
| `found_again` | true/false | Whether the later flight found a hotspot at the same spot. |
| `later_hotspot_uid` | text | That hotspot, if found. |
| `rise_before_c` | number | Temperature rise when first seen, in °C. |
| `rise_at_revisit_c` | number | Temperature rise on the later flight, if found. |
| `rise_change_c` | number | rise_at_revisit_c minus rise_before_c. |
| `outcome` | text | repair_held, came_back_after_repair, still_hot, not_seen_again, dismissed_seen_again or dismissed_not_seen. |
| `nearest_photo_m` | number | How close the later flight's nearest photo was to the spot, in metres. Smaller is a surer check. |

## Revisit outcomes

A revisit row is written for every hotspot and every later flight whose photos came within `nearest_photo_m` of the spot (most of the half-width of a straight-down photo at the flight's standoff). Its status is taken as it stood when that later flight was flown.

| Status at the later flight | Found again | Outcome |
|---|---|---|
| repaired | no | `repair_held` |
| repaired | yes | `came_back_after_repair` |
| open | yes | `still_hot` |
| open | no | `not_seen_again` |
| dismissed | yes | `dismissed_seen_again` |
| dismissed | no | `dismissed_not_seen` |
