# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""LineGuard open data: every flight, hotspot, status change and revisit as documented tables
that reporting tools (Power BI, Databricks, Excel, any SQL engine) load as they are.

The format is described once, in TABLES below. The Parquet and CSV files, the Frictionless
Data Package descriptor (datapackage.json) and docs/data-format.md are all generated from it,
so they can't drift apart.

Times: every column ending in _utc is UTC. flown_at_local is the drone's own clock, which has
no time zone; flown_at_utc converts it with the camera_timezone setting.
"""
from __future__ import annotations

import csv
import io
import json
import math
import uuid
import zipfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import __version__
from .exports import _cell, maps_link

FORMAT_VERSION = "1.0"
FORMAT_URL = "https://github.com/OpenWorksIT/lineguard/blob/main/docs/data-format.md"
# a fixed namespace, so a revisit's ID is the same in every export (safe to MERGE on)
_NS = uuid.UUID("6b1f3c2e-4a7d-5e8f-9b0a-1c2d3e4f5a6b")

SEVERITY_RANK = {"possible": 1, "probable": 2, "major": 3}
OUTCOMES = {
    # (status when the later flight flew, found again?) -> outcome
    ("repaired", False): "repair_held",
    ("repaired", True): "came_back_after_repair",
    ("open", True): "still_hot",
    ("open", False): "not_seen_again",
    ("dismissed", True): "dismissed_seen_again",
    ("dismissed", False): "dismissed_not_seen",
}

# name, type, description. Types: string, integer, number, boolean, datetime (UTC), localtime (no zone)
TABLES = {
    "sites": {
        "title": "The LineGuard server or laptop this export came from",
        "key": "site_id",
        "fields": [
            ("site_id", "string", "Permanent ID of this LineGuard installation. Every other table carries it, so exports from several sites can be stacked."),
            ("site_name", "string", "The name this LineGuard shows on phones."),
            ("lineguard_version", "string", "LineGuard version that wrote the export."),
            ("data_format_version", "string", "Version of this data format."),
            ("exported_at_utc", "datetime", "When the export was made."),
            ("camera_timezone", "string", "Time zone used to turn the drone's clock into UTC."),
        ],
    },
    "flights": {
        "title": "One row per processed drone flight",
        "key": "flight_uid",
        "foreign": [("site_id", "sites", "site_id")],
        "fields": [
            ("site_id", "string", "The site this flight belongs to."),
            ("flight_uid", "string", "Permanent ID of the flight."),
            ("flight_number", "integer", "The flight's number on the dashboard (only unique within one site)."),
            ("flight_name", "string", "Name given to the flight (usually its folder name)."),
            ("flown_at_local", "localtime", "When the first photo was taken, by the drone's clock."),
            ("flown_at_utc", "datetime", "flown_at_local converted to UTC with camera_timezone. Use this to compare flights with repairs."),
            ("added_at_utc", "datetime", "When the flight was added to LineGuard."),
            ("processing_status", "string", "queued, processing, done or failed."),
            ("photos", "integer", "Thermal photos in the flight."),
            ("photos_skipped", "integer", "Photos that could not be used (not looking straight down, unreadable)."),
            ("lines_found", "integer", "Photos in which the conductors were found."),
            ("candidates_rejected", "integer", "Hot spots seen in one photo only and therefore dropped."),
            ("standoff_m", "number", "Distance from the camera to the conductors, in metres."),
            ("centre_latitude", "number", "Middle of the flight, WGS84."),
            ("centre_longitude", "number", "Middle of the flight, WGS84."),
            ("hotspots", "integer", "Confirmed hotspots in this flight."),
            ("hotspots_open", "integer", "Of those, how many are still open."),
            ("major_open", "integer", "Open hotspots rated major."),
        ],
    },
    "hotspots": {
        "title": "One row per confirmed hotspot, with its current status",
        "key": "hotspot_uid",
        "foreign": [("site_id", "sites", "site_id"), ("flight_uid", "flights", "flight_uid")],
        "fields": [
            ("site_id", "string", "The site this hotspot belongs to."),
            ("hotspot_uid", "string", "Permanent ID of the hotspot. Survives reprocessing the flight."),
            ("label", "string", "The hotspot's name on the dashboard and phones, e.g. LG-12 (only unique within one site)."),
            ("flight_uid", "string", "The flight that found it."),
            ("place_uid", "string", "The same spot across all flights: every sighting of one fault position shares this ID (it is the hotspot_uid of the first sighting)."),
            ("previous_hotspot_uid", "string", "The nearest hotspot at the same spot on an earlier flight, if there was one."),
            ("sighting_number", "integer", "1 for the first time this spot was found, 2 for the second flight that found it, and so on."),
            ("is_latest_sighting", "boolean", "True for the most recent sighting of this spot. Count open faults with is_open and is_latest_sighting, so a fault seen on several flights counts once."),
            ("recurring", "boolean", "True if this spot had been marked repaired before this flight and the fault is back."),
            ("repairs_before", "integer", "How many earlier sightings of this spot had been marked repaired before this flight."),
            ("latitude", "number", "WGS84."),
            ("longitude", "number", "WGS84."),
            ("temperature_rise_c", "number", "How much hotter than the other phases at the same point, in °C."),
            ("previous_rise_c", "number", "The rise at the same spot on the earlier flight."),
            ("rise_change_c", "number", "temperature_rise_c minus previous_rise_c. Positive means getting hotter."),
            ("severity", "string", "possible (under 4 °C), probable (4 to 15 °C) or major (over 15 °C), after NETA similar-component bands."),
            ("severity_rank", "integer", "1 possible, 2 probable, 3 major. Sort and filter by this."),
            ("status", "string", "open, repaired or dismissed (not a fault)."),
            ("is_open", "boolean", "True while the status is open."),
            ("found_at_utc", "datetime", "When LineGuard found it."),
            ("flown_at_utc", "datetime", "When the flight that found it was flown."),
            ("status_changed_at_utc", "datetime", "When the status last changed (blank while it has never changed)."),
            ("status_changed_by", "string", "Phone or dashboard that last changed the status."),
            ("repaired_at_utc", "datetime", "When it was marked repaired, if its status is repaired."),
            ("days_open", "number", "Days from the flight to the repair, or to the export while still open."),
            ("note", "string", "The latest note from a technician."),
            ("photos_confirming", "integer", "Photos the hotspot was seen in."),
            ("photos_covering", "integer", "Photos that covered the spot."),
            ("photo_name", "string", "The best photo of it."),
            ("tower_ref", "string", "Nearest tower or pole, from the client's tower list or OpenStreetMap."),
            ("tower_kind", "string", "tower or pole."),
            ("tower_distance_m", "number", "Distance to that tower, in metres."),
            ("line_name", "string", "Power line name, where known."),
            ("line_voltage_kv", "number", "Line voltage in kV, where known."),
            ("line_operator", "string", "Line operator, where known."),
            ("google_maps_url", "string", "Link that opens the position in Google Maps."),
        ],
    },
    "hotspot_events": {
        "title": "Every hotspot's history: found, status changes, notes, and gone after reprocessing. Rows are only ever added",
        "key": "event_uid",
        "foreign": [("site_id", "sites", "site_id")],
        "fields": [
            ("site_id", "string", "The site this event belongs to."),
            ("event_uid", "string", "Permanent ID of the event."),
            ("hotspot_uid", "string", "The hotspot it happened to. A 'gone' hotspot no longer appears in the hotspots table."),
            ("event_number", "integer", "Order of events within one site."),
            ("at_utc", "datetime", "When it happened. Changes made on a phone without signal carry the time they were made, not the time they were sent."),
            ("kind", "string", "found, status, note or gone (processing the flight again no longer finds it)."),
            ("status", "string", "The new status, for found and status events."),
            ("note", "string", "The note, for note and gone events."),
            ("changed_by", "string", "Phone or dashboard that made the change."),
        ],
    },
    "revisits": {
        "title": "Each later flight that passed over a hotspot's spot, and what it found there",
        "key": "revisit_uid",
        "foreign": [("site_id", "sites", "site_id"), ("hotspot_uid", "hotspots", "hotspot_uid"),
                    ("revisit_flight_uid", "flights", "flight_uid")],
        "fields": [
            ("site_id", "string", "The site."),
            ("revisit_uid", "string", "Permanent ID of this hotspot-and-flight pair (the same in every export)."),
            ("hotspot_uid", "string", "The hotspot being checked."),
            ("place_uid", "string", "The spot, as in the hotspots table."),
            ("revisit_flight_uid", "string", "The later flight that covered the spot."),
            ("hotspot_flown_at_utc", "datetime", "When the hotspot was first seen."),
            ("revisit_flown_at_utc", "datetime", "When the later flight flew over it."),
            ("days_between", "number", "Days between the two flights."),
            ("status_at_revisit", "string", "The hotspot's status when the later flight flew: open, repaired or dismissed."),
            ("repaired_at_utc", "datetime", "When it was marked repaired, if that was before the later flight."),
            ("days_repair_to_revisit", "number", "Days from the repair to the later flight."),
            ("found_again", "boolean", "Whether the later flight found a hotspot at the same spot."),
            ("later_hotspot_uid", "string", "That hotspot, if found."),
            ("rise_before_c", "number", "Temperature rise when first seen, in °C."),
            ("rise_at_revisit_c", "number", "Temperature rise on the later flight, if found."),
            ("rise_change_c", "number", "rise_at_revisit_c minus rise_before_c."),
            ("outcome", "string", "repair_held, came_back_after_repair, still_hot, not_seen_again, dismissed_seen_again or dismissed_not_seen."),
            ("nearest_photo_m", "number", "How close the later flight's nearest photo was to the spot, in metres. Smaller is a surer check."),
        ],
    },
}


# ---------- time helpers
def _utc(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _camera_time(value) -> datetime | None:
    """The drone's clock as written in EXIF (2026:11:27 08:15:02) or ISO, without a zone."""
    if not value:
        return None
    v = str(value).strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(v[:19], fmt)
        except ValueError:
            continue
    return None


def camera_zone(settings):
    if getattr(settings, "camera_timezone", ""):
        return ZoneInfo(settings.camera_timezone)
    return datetime.now().astimezone().tzinfo


def _days(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 86400, 2)


def _metres(lat0, lon0, lat, lon):
    k = math.cos(math.radians(lat0))
    return math.hypot((lon - lon0) * 111320 * k, (lat - lat0) * 110540)


# ---------- building the tables
def build(store, settings, at: datetime | None = None, with_revisits=True) -> dict[str, list[dict]]:
    at = at or datetime.now(timezone.utc).replace(microsecond=0)
    site = store.site_id
    zone = camera_zone(settings)
    zone_name = getattr(settings, "camera_timezone", "") or str(zone)

    flights_raw = {f["id"]: f for f in store.flights()}
    full = {fid: store.flight(fid) for fid in flights_raw}       # flights() leaves nothing out, but be explicit
    hs = store.hotspots()
    events = store.events()

    def flown_utc(f):
        local = _camera_time(f["flown"])
        return local.replace(tzinfo=zone).astimezone(timezone.utc) if local else None

    flight_time = {}
    flights = []
    for fid, f in sorted(flights_raw.items()):
        local = _camera_time(f["flown"])
        utc = flown_utc(f)
        flight_time[fid] = utc or _utc(f["created"])
        flights.append({
            "site_id": site, "flight_uid": f["uid"], "flight_number": fid, "flight_name": f["name"],
            "flown_at_local": local, "flown_at_utc": utc, "added_at_utc": _utc(f["created"]),
            "processing_status": f["status"], "photos": f["photos"], "photos_skipped": f["photos_skipped"],
            "lines_found": f["lines_found"], "candidates_rejected": f["rejected"], "standoff_m": f["standoff_m"],
            "centre_latitude": f["lat"], "centre_longitude": f["lon"], "hotspots": f["hotspots"] or 0,
            "hotspots_open": f["open"] or 0, "major_open": f["major_open"] or 0,
        })

    # history per hotspot, oldest first
    history: dict[str, list[dict]] = {}
    for e in events:
        history.setdefault(e["hotspot_uid"], []).append(e)
    far = datetime.max.replace(tzinfo=timezone.utc)
    for rows in history.values():
        rows.sort(key=lambda e: (_utc(e["at"]) or far, e["id"]))

    def status_at(uid, when):
        """(status, repaired_at) as they stood at a moment, from the history."""
        status, repaired = "open", None
        for e in history.get(uid, []):
            t = _utc(e["at"])
            if when is not None and t is not None and t > when:
                break
            if e["kind"] == "status" and e["status"]:
                status = e["status"]
                repaired = t if status == "repaired" else None
        return status, repaired

    by_uid = {h["uid"]: h for h in hs}

    def place_of(h):
        seen, cur = set(), h
        while cur.get("prev_uid") and cur["prev_uid"] in by_uid and cur["uid"] not in seen:
            seen.add(cur["uid"])
            cur = by_uid[cur["prev_uid"]]
        return cur["uid"]

    hotspots = []
    for h in sorted(hs, key=lambda r: r["id"]):
        mine = history.get(h["uid"], [])
        found = next((_utc(e["at"]) for e in mine if e["kind"] == "found"), None)
        last_status = next((e for e in reversed(mine) if e["kind"] == "status"), None)
        status, repaired = status_at(h["uid"], None)
        if status != h["status"]:            # history older than 0.4: trust the current row
            status, repaired = h["status"], _utc(h["updated"]) if h["status"] == "repaired" else None
        flown = flight_time.get(h["flight_id"])
        end = repaired if status == "repaired" else (at if status == "open" else None)
        hotspots.append({
            "site_id": site, "hotspot_uid": h["uid"], "label": f"LG-{h['id']}",
            "flight_uid": flights_raw[h["flight_id"]]["uid"], "place_uid": place_of(h),
            "previous_hotspot_uid": h.get("prev_uid") if h.get("prev_uid") in by_uid else None,
            "latitude": h["lat"], "longitude": h["lon"], "temperature_rise_c": h["dt"],
            "previous_rise_c": h["prev_dt"],
            "rise_change_c": round(h["dt"] - h["prev_dt"], 2) if h["prev_dt"] is not None else None,
            "severity": h["severity"], "severity_rank": SEVERITY_RANK.get(h["severity"]),
            "status": h["status"], "is_open": h["status"] == "open",
            "found_at_utc": found, "flown_at_utc": flown,
            "status_changed_at_utc": _utc(last_status["at"]) if last_status else None,
            "status_changed_by": (last_status["by"] or None) if last_status else (h.get("updated_by") or None),
            "repaired_at_utc": repaired if status == "repaired" else None,
            "days_open": _days(flown, end),
            "note": h["note"] or None, "photos_confirming": h["photos"], "photos_covering": h["seen"],
            "photo_name": h["photo_name"] or None, "tower_ref": h.get("tower_ref"), "tower_kind": h.get("tower_kind"),
            "tower_distance_m": h.get("tower_dist_m"), "line_name": h.get("line_name"),
            "line_voltage_kv": h.get("line_voltage_kv"), "line_operator": h.get("line_operator"),
            "google_maps_url": maps_link(h["lat"], h["lon"]),
        })
    place = {r["hotspot_uid"]: r["place_uid"] for r in hotspots}
    _sightings(hotspots, status_at)

    hotspot_events = [{
        "site_id": site, "event_uid": e["uid"], "hotspot_uid": e["hotspot_uid"], "event_number": e["id"],
        "at_utc": _utc(e["at"]), "kind": e["kind"], "status": e["status"], "note": e["note"],
        "changed_by": e["by"] or None,
    } for e in events]

    revisits = _revisits(site, settings, full, flight_time, hs, status_at, place) if with_revisits else []

    sites = [{"site_id": site, "site_name": settings.display_name, "lineguard_version": __version__,
              "data_format_version": FORMAT_VERSION, "exported_at_utc": at, "camera_timezone": zone_name}]
    return {"sites": sites, "flights": flights, "hotspots": hotspots,
            "hotspot_events": hotspot_events, "revisits": revisits}


def _sightings(hotspots, status_at):
    """Number each spot's sightings in flight order and flag faults that came back after a repair."""
    far = datetime.max.replace(tzinfo=timezone.utc)
    places: dict[str, list[dict]] = {}
    for r in hotspots:
        places.setdefault(r["place_uid"], []).append(r)
    for rows in places.values():
        rows.sort(key=lambda r: (r["flown_at_utc"] or far, r["label"]))
        for i, r in enumerate(rows):
            t = r["flown_at_utc"]
            repaired = sum(1 for e in rows[:i] if status_at(e["hotspot_uid"], t)[0] == "repaired")
            r.update(sighting_number=i + 1, is_latest_sighting=i == len(rows) - 1,
                     recurring=repaired > 0, repairs_before=repaired)


def recurring_uids(store, settings) -> dict[str, dict]:
    """For the dashboard: each hotspot's sighting number and whether it came back after a repair."""
    t = build(store, settings, with_revisits=False)
    return {r["hotspot_uid"]: {k: r[k] for k in ("sighting_number", "is_latest_sighting", "recurring", "repairs_before")}
            for r in t["hotspots"]}


def _coverage(f) -> list:
    pts = json.loads(f.get("coverage") or "[]") or json.loads(f.get("track") or "[]")
    return [p for p in pts if isinstance(p, list) and len(p) == 2]


def coverage_radius(settings, f) -> float:
    """How far from a photo's position a spot still counts as photographed: most of the half-width
    of a straight-down thermal photo at the flight's standoff."""
    standoff = f.get("standoff_m") or settings.detection.standoff_m
    return 0.7 * standoff * math.tan(math.radians(settings.camera.diagonal_fov_deg / 2))


def _revisits(site, settings, flights, flight_time, hs, status_at, place):
    import numpy as np

    by_flight: dict[int, list[dict]] = {}
    for h in hs:
        by_flight.setdefault(h["flight_id"], []).append(h)
    cover = {}
    for fid, f in flights.items():
        pts = np.array(_coverage(f), float).reshape(-1, 2)
        cover[fid] = pts
    match_r = settings.detection.history_radius_m
    rows = []
    for h in hs:
        t0 = flight_time.get(h["flight_id"])
        if t0 is None:
            continue
        for fid, f in flights.items():
            t1 = flight_time.get(fid)
            if fid == h["flight_id"] or t1 is None or t1 <= t0 or f["status"] != "done":
                continue
            pts = cover[fid]
            if not len(pts):
                continue
            k = math.cos(math.radians(h["lat"]))
            d = np.hypot((pts[:, 1] - h["lon"]) * 111320 * k, (pts[:, 0] - h["lat"]) * 110540)
            nearest = float(d.min())
            if nearest > coverage_radius(settings, f):
                continue
            again = min(((_metres(h["lat"], h["lon"], o["lat"], o["lon"]), o) for o in by_flight.get(fid, [])),
                        key=lambda x: x[0], default=(None, None))
            later = again[1] if again[0] is not None and again[0] <= match_r else None
            status, repaired = status_at(h["uid"], t1)
            rows.append({
                "site_id": site,
                "revisit_uid": str(uuid.uuid5(_NS, f"{h['uid']}|{f['uid']}")),
                "hotspot_uid": h["uid"], "place_uid": place.get(h["uid"]), "revisit_flight_uid": f["uid"],
                "hotspot_flown_at_utc": t0, "revisit_flown_at_utc": t1, "days_between": _days(t0, t1),
                "status_at_revisit": status, "repaired_at_utc": repaired,
                "days_repair_to_revisit": _days(repaired, t1),
                "found_again": later is not None, "later_hotspot_uid": later["uid"] if later else None,
                "rise_before_c": h["dt"], "rise_at_revisit_c": later["dt"] if later else None,
                "rise_change_c": round(later["dt"] - h["dt"], 2) if later else None,
                "outcome": OUTCOMES.get((status, later is not None)),
                "nearest_photo_m": round(nearest, 1),
            })
    rows.sort(key=lambda r: (r["revisit_flown_at_utc"], r["hotspot_uid"]))
    return rows


# ---------- writing
def _iso(v, kind):
    if v is None:
        return ""
    if kind == "datetime":
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if kind == "localtime":
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def to_csv(name, rows) -> str:
    fields = TABLES[name]["fields"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([f[0] for f in fields])
    for r in rows:
        w.writerow([_cell(_iso(r[n], t)) for n, t, _ in fields])
    return buf.getvalue()


def _arrow_schema(name):
    import pyarrow as pa

    types = {"string": pa.string(), "integer": pa.int64(), "number": pa.float64(), "boolean": pa.bool_(),
             "datetime": pa.timestamp("us", tz="UTC"), "localtime": pa.timestamp("us")}
    meta = {b"lineguard.table": name.encode(), b"lineguard.format_version": FORMAT_VERSION.encode()}
    return pa.schema([pa.field(n, types[t], metadata={b"description": d.encode()})
                      for n, t, d in TABLES[name]["fields"]], metadata=meta)


def to_parquet(name, rows) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = _arrow_schema(name)
    cols = {}
    for n, t, _ in TABLES[name]["fields"]:
        vals = [r[n] for r in rows]
        if t == "datetime":
            vals = [v.astimezone(timezone.utc) if v else None for v in vals]
        cols[n] = vals
    table = pa.Table.from_pydict(cols, schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def descriptor(at: datetime, formats=("csv", "parquet")) -> dict:
    """Frictionless Data Package (https://datapackage.org) describing the tables."""
    ftype = {"localtime": "datetime"}
    resources = []
    for fmt in formats:
        for name, t in TABLES.items():
            schema = {
                "fields": [{"name": n, "type": ftype.get(ty, ty), "description": d}
                           | ({"format": "%Y-%m-%dT%H:%M:%SZ"} if ty == "datetime" else {})
                           | ({"format": "%Y-%m-%dT%H:%M:%S"} if ty == "localtime" else {})
                           for n, ty, d in t["fields"]],
                "primaryKey": [t["key"]],
                "missingValues": [""],
            }
            if t.get("foreign"):
                schema["foreignKeys"] = [{"fields": [c], "reference": {"resource": f"{ref}{'' if fmt == 'csv' else '_parquet'}",
                                                                       "fields": [rc]}} for c, ref, rc in t["foreign"]]
            res = {"name": name if fmt == "csv" else f"{name}_parquet", "path": f"{name}.{fmt}",
                   "title": t["title"], "format": fmt}
            if fmt == "csv":
                res |= {"profile": "tabular-data-resource", "mediatype": "text/csv", "encoding": "utf-8", "schema": schema}
            else:
                res |= {"profile": "data-resource", "mediatype": "application/vnd.apache.parquet", "schema": schema}
            resources.append(res)
    return {
        "profile": "data-package", "name": "lineguard-data", "title": "LineGuard hotspot data",
        "version": FORMAT_VERSION, "created": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "homepage": FORMAT_URL,
        "description": "Flights, hotspots, their history and revisits from LineGuard. Times ending in _utc are UTC.",
        "sources": [{"title": f"LineGuard {__version__}", "path": "https://github.com/OpenWorksIT/lineguard"}],
        "resources": resources,
    }


def markdown() -> str:
    """The format reference: docs/data-format.md and the README inside each export."""
    kinds = {"string": "text", "integer": "whole number", "number": "number", "boolean": "true/false",
             "datetime": "date-time, UTC", "localtime": "date-time, drone clock"}
    out = [f"# LineGuard open data format {FORMAT_VERSION}", "",
           "Generated from `lineguard/opendata.py`; don't edit by hand.", "",
           "Every export has the same five tables, each as Parquet (typed) and CSV (UTF-8, comma separated, "
           "ISO 8601 times). `datapackage.json` describes them in the open "
           "[Frictionless Data Package](https://datapackage.org) standard.", "",
           "* IDs ending in `_uid` are permanent and unique across every LineGuard installation, so exports "
           "from several sites can be stacked into one table.",
           "* Columns ending in `_utc` are UTC. `flown_at_local` is the drone's own clock; "
           "`flown_at_utc` converts it with the `camera_timezone` setting.",
           "* Blank means not known or not applicable.",
           "* Text that starts with `=`, `+`, `-` or `@` gets a leading `'` in the CSV files only, so a spreadsheet "
           "doesn't run it as a formula. The Parquet files hold the text unchanged.",
           "* The data is small (thousands of rows), so the simplest load is to replace every table on each refresh. "
           "To merge instead, use the `_uid` key of each table.", "",
           "## How the tables fit together", "",
           "```",
           "sites 1──* flights 1──* hotspots 1──* hotspot_events",
           "                          │  └─ place_uid groups sightings of one spot across flights",
           "                          └──* revisits *──1 flights (the later flight)",
           "```", ""]
    for name, t in TABLES.items():
        out += [f"## {name}", "", t["title"] + ".", "", f"Key: `{t['key']}`", "",
                "| Column | Type | Meaning |", "|---|---|---|"]
        out += [f"| `{n}` | {kinds[ty]} | {d} |" for n, ty, d in t["fields"]]
        out.append("")
    out += ["## Revisit outcomes", "",
            "A revisit row is written for every hotspot and every later flight whose photos came within "
            "`nearest_photo_m` of the spot (most of the half-width of a straight-down photo at the flight's standoff). "
            "Its status is taken as it stood when that later flight was flown.", "",
            "| Status at the later flight | Found again | Outcome |", "|---|---|---|"]
    out += [f"| {s} | {'yes' if f else 'no'} | `{o}` |" for (s, f), o in OUTCOMES.items()]
    out.append("")
    return "\n".join(out)


# ---------- Power BI (Power Query M), generated so the column types always match the format
_M_TYPES = {"string": "type text", "integer": "Int64.Type", "number": "type number", "boolean": "type logical",
            "datetime": "type datetimezone", "localtime": "type datetime"}


def power_query_function() -> str:
    return """// LineGuardTable: reads one LineGuard table. Make it once as a blank query named LineGuardTable.
// It reads the live feed by default. LineGuardFeed is a text parameter holding the feed address,
// e.g. https://lineguard.example.com/api/data/v1/  (Manage parameters → New parameter).
// Credentials: Basic, user name "data", password = a data key from the LineGuard dashboard.
// To read exported files from a SharePoint or OneDrive folder instead, use the second Source line.
(name as text) as table =>
let
    Source = Web.Contents(LineGuardFeed, [RelativePath = name & ".csv", Headers = [Accept = "text/csv"]]),
    // Source = SharePoint.Files("https://contoso.sharepoint.com/sites/assets", [ApiVersion = 15]){[Name = name & ".csv", #"Folder Path" = "https://contoso.sharepoint.com/sites/assets/Shared Documents/LineGuard/"]}[Content],
    Csv = Csv.Document(Source, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Csv, [PromoteAllScalars = true]),
    // a blank cell means "not known": make it null before the columns are typed
    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted))
in
    Blanks
"""


def power_query(name) -> str:
    """One query per table: load it and give every column its proper type."""
    types = ",\n        ".join(f'{{"{n}", {_M_TYPES[t]}}}' for n, t, _ in TABLES[name]["fields"])
    return f"""// LineGuard {name}: {TABLES[name]["title"]}.
// Generated from LineGuard's data format {FORMAT_VERSION}; see docs/data-format.md.
let
    Source = LineGuardTable("{name}"),
    // en-US: the files always use a full stop for decimals, whatever this computer's region
    Typed = Table.TransformColumnTypes(Source, {{
        {types}
    }}, "en-US")
in
    Typed
"""


def package(store, settings, at: datetime | None = None) -> bytes:
    """Everything in one zip: Parquet, CSV, datapackage.json and README.md."""
    at = at or datetime.now(timezone.utc).replace(microsecond=0)
    data = build(store, settings, at)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rows in data.items():
            z.writestr(f"{name}.parquet", to_parquet(name, rows))
            z.writestr(f"{name}.csv", to_csv(name, rows))
        z.writestr("datapackage.json", json.dumps(descriptor(at), indent=1, ensure_ascii=False))
        z.writestr("README.md", markdown())
    return buf.getvalue()


def write_folder(store, settings, folder, formats=("parquet", "csv")) -> list[str]:
    """Write the tables into a folder (for a synced OneDrive/SharePoint folder or a Databricks volume).
    Each file is written beside the old one and then swapped in, so a reader never sees half a file."""
    from pathlib import Path

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    at = datetime.now(timezone.utc).replace(microsecond=0)
    data = build(store, settings, at)
    written = []

    def put(name, content):
        tmp = folder / f".{name}.tmp"
        tmp.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        tmp.replace(folder / name)
        written.append(name)

    for name, rows in data.items():
        if "parquet" in formats:
            put(f"{name}.parquet", to_parquet(name, rows))
        if "csv" in formats:
            put(f"{name}.csv", to_csv(name, rows))
    put("datapackage.json", json.dumps(descriptor(at, formats=tuple(f for f in ("csv", "parquet") if f in formats)),
                                       indent=1, ensure_ascii=False))
    put("README.md", markdown())
    return written
