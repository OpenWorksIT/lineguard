# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Power lines, towers and substations from OpenStreetMap (the data behind
openinframap.org), fetched once per flight through the Overpass API and
cached, so each hotspot can be labelled with its nearest tower.

Data © OpenStreetMap contributors, ODbL. Fetching needs internet; when there
is none the flight simply has no power layer until "Load power lines" is
pressed again with a connection.
"""
from __future__ import annotations

import json
import re
import math
import urllib.error
import urllib.parse
import urllib.request

from .geo import LocalFrame

LINE_KINDS = ("line", "minor_line", "cable")
SUPPORT_KINDS = ("tower", "pole", "portal", "terminal", "insulator")
AREA_KINDS = ("substation", "plant", "generator", "transformer", "switch")


def query(south, west, north, east) -> str:
    bb = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    return (f'[out:json][timeout:60];('
            f'way["power"~"^({"|".join(LINE_KINDS)})$"]({bb});'
            f'node["power"~"^({"|".join(SUPPORT_KINDS)})$"]({bb});'
            f'way["power"~"^(substation|plant)$"]({bb});'
            f'node["power"="generator"]({bb});'
            f');out tags geom;')


def bbox_around(points, margin_m=300.0):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    mlat = margin_m / 111_320
    mlon = margin_m / (111_320 * max(0.2, math.cos(math.radians(sum(lats) / len(lats)))))
    return min(lats) - mlat, min(lons) - mlon, max(lats) + mlat, max(lons) + mlon


def fetch(points, overpass_url, timeout=60) -> dict:
    data = urllib.parse.urlencode({"data": query(*bbox_around(points))}).encode()
    req = urllib.request.Request(overpass_url, data=data,
                                 headers={"User-Agent": "LineGuard (OpenWorks IT) +https://www.openworks.co.za"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return simplify(json.load(r))


def _voltage_kv(v: str | None):
    """'132000;33000' -> 132.0 (highest), None if unknown."""
    best = None
    for part in (v or "").replace(",", ";").split(";"):
        try:
            kv = float(part.strip()) / 1000
        except ValueError:
            continue
        if not math.isfinite(kv) or kv <= 0:
            continue
        best = kv if best is None else max(best, kv)
    return best


def simplify(raw: dict) -> dict:
    """Overpass JSON -> the compact form stored with a flight and sent to the dashboard and app."""
    lines, supports, areas = [], [], []
    for el in raw.get("elements", []) if isinstance(raw, dict) else []:
        try:
            if not isinstance(el, dict) or not isinstance(el.get("tags", {}), dict):
                continue
            t = el.get("tags", {})
            kind = t.get("power")
            if el.get("type") == "way" and kind in LINE_KINDS and el.get("geometry"):
                lines.append({"id": el["id"], "kind": kind, "name": clean_text(t.get("name") or t.get("ref"))[:80],
                              "voltage_kv": _voltage_kv(t.get("voltage")), "operator": clean_text(t.get("operator"))[:80],
                              "coords": [[round(g["lat"], 7), round(g["lon"], 7)] for g in el["geometry"]]})
            elif el.get("type") == "node" and kind in SUPPORT_KINDS and "lat" in el and "lon" in el:
                supports.append({"id": el["id"], "kind": kind, "ref": clean_text(t.get("ref"))[:40],
                                 "operator": clean_text(t.get("operator"))[:80], "lat": float(el["lat"]), "lon": float(el["lon"])})
            elif kind in ("substation", "plant", "generator"):
                if el.get("type") == "node" and "lat" in el and "lon" in el:
                    c = [float(el["lat"]), float(el["lon"])]
                elif el.get("geometry"):
                    c = [sum(g["lat"] for g in el["geometry"]) / len(el["geometry"]),
                         sum(g["lon"] for g in el["geometry"]) / len(el["geometry"])]
                else:
                    continue
                areas.append({"id": el["id"], "kind": kind, "name": clean_text(t.get("name"))[:80],
                              "source": clean_text(t.get("plant:source") or t.get("generator:source"))[:40],
                              "lat": c[0], "lon": c[1]})
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue  # skip anything malformed in the reply
    return {"lines": lines, "supports": supports, "areas": areas,
            "attribution": "© OpenStreetMap contributors (ODbL)"}


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def nearest(power: dict, lat: float, lon: float, support_radius=60.0, line_radius=40.0) -> dict:
    """Nearest tower or pole and nearest line to a hotspot, within the given radii (metres)."""
    f = LocalFrame(lat, lon)
    out = {}
    best = None
    for s in power.get("supports", []):
        d = math.hypot(*f.to_xy(s["lat"], s["lon"]))
        if d <= support_radius and (best is None or d < best[0]):
            best = (d, s)
    if best:
        d, s = best
        out.update(tower_ref=s["ref"] or f"OSM node {s['id']}", tower_kind=s["kind"], tower_dist_m=round(d, 1))
        if s.get("source") == "client" and s.get("operator"):
            out["line_name"] = s["operator"]
    best = None
    for line in power.get("lines", []):
        pts = [f.to_xy(*c) for c in line["coords"]]
        d = min((_seg_dist((0, 0), pts[i], pts[i + 1]) for i in range(len(pts) - 1)), default=1e9)
        if d <= line_radius and (best is None or d < best[0]):
            best = (d, line)
    if best:
        line = best[1]
        if not out.get("line_name"):
            out["line_name"] = line["name"]
        out.update(line_voltage_kv=line["voltage_kv"], line_operator=line["operator"])
    return out


def label(h: dict) -> str:
    """'Tower 47, Kappa 132 kV line' style label from a hotspot row."""
    parts = []
    if h.get("tower_ref"):
        parts.append(f"{(h.get('tower_kind') or 'tower').capitalize()} {h['tower_ref']}")
    line = h.get("line_name") or ""
    kv = h.get("line_voltage_kv")
    if line or kv:
        parts.append(" ".join(x for x in (line, f"{kv:g} kV" if kv else "", "line") if x))
    return ", ".join(parts)


def with_client_towers(store, power: dict | None, points) -> dict:
    """OSM power data plus the client's own towers near these points."""
    power = dict(power or {"lines": [], "supports": [], "areas": []})
    if points:
        s, w, n, e = bbox_around(points)
        mine = [{"id": f"c{t['id']}", "kind": "tower", "ref": t["ref"], "operator": t["line"], "lat": t["lat"],
                 "lon": t["lon"], "source": "client"} for t in store.towers(s, w, n, e)]
        power["supports"] = mine + list(power.get("supports", []))
    return power


def label_hotspots(store, fid, power):
    for h in store.hotspots(fid):
        vals = {k: None for k in POWER_COLS}
        near = nearest(power, h["lat"], h["lon"])
        # a client tower carries its line name in "operator"
        vals.update(near)
        store.set_hotspot_power(h["id"], **vals)


def flight_points(store, fid):
    flight = store.flight(fid)
    return json.loads(flight["track"] or "[]") + [[h["lat"], h["lon"]] for h in store.hotspots(fid)]


def attach(store, settings, fid, fetch_osm=True) -> str:
    """Label a flight's hotspots with the nearest tower: the client's register always, OpenStreetMap when online."""
    pts = flight_points(store, fid)
    if not pts:
        return "Nothing to look up yet."
    msg = ""
    power = None
    if fetch_osm:
        try:
            power = fetch(pts, settings.overpass_url)
            store.update_flight(fid, power=json.dumps(power))
            msg = f"{len(power['lines'])} power lines and {len(power['supports'])} towers or poles from OpenStreetMap."
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            msg = f"OpenStreetMap power data is not available right now ({e.__class__.__name__})."
    if power is None:
        raw = store.flight(fid)["power"]
        power = json.loads(raw) if raw else None
    merged = with_client_towers(store, power, pts)
    label_hotspots(store, fid, merged)
    mine = sum(1 for s_ in merged["supports"] if s_.get("source") == "client")
    if mine:
        msg += f" {mine} of your own towers in this area."
    return msg.strip()


def _between(text: str, start: str, end: str):
    """Text between the first start tag and its end tag (case-insensitive), scanning forward only."""
    low = text.lower()
    a = low.find(start)
    if a < 0:
        return None, -1
    a = low.find(">", a)
    if a < 0:
        return None, -1
    b = low.find(end, a)
    if b < 0:
        return None, -1
    return text[a + 1:b], b + len(end)


def _kml_points(text: str) -> list[dict]:
    """Placemark points from KML, read in one forward pass (no backtracking regexes)."""
    import re as _re
    rows, pos, low = [], 0, text.lower()
    while len(rows) < 100_000:
        a = low.find("<placemark", pos)
        if a < 0:
            break
        b = low.find("</placemark>", a)
        if b < 0:
            break
        pm = text[a:b]
        pos = b + 12
        name, _ = _between(pm, "<name", "</name>")
        coords, _ = _between(pm, "<coordinates", "</coordinates>")
        if coords is None or "<point" not in pm.lower():
            continue
        m = _re.match(r"\s*([-\d.]+)\s*,\s*([-\d.]+)", coords)
        if not m:
            continue
        ref = (name or "").strip()
        if ref.startswith("<![CDATA[") and ref.endswith("]]>"):
            ref = ref[9:-3].strip()
        rows.append({"ref": ref[:40], "lat": float(m.group(2)), "lon": float(m.group(1))})
    return rows


class TowerFileError(ValueError):
    """A tower file problem with a message that's safe to show the user."""


def _point(coords) -> tuple[float, float]:
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        raise TowerFileError("A GeoJSON point is missing its coordinates.")
    try:
        return float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        raise TowerFileError("A GeoJSON point has coordinates that aren't numbers.") from None


def parse_towers(filename: str, data: bytes) -> list[dict]:
    """Towers from CSV (ref, lat, lon[, line]), KML placemarks or GeoJSON points."""
    name = filename.lower()
    text = data.decode("utf-8-sig", "replace")
    rows = []
    if name.endswith((".kml", ".xml")):
        rows = _kml_points(text)
    elif name.endswith((".geojson", ".json")):
        try:
            doc = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            raise TowerFileError("That GeoJSON file isn't valid JSON.") from None
        feats = doc.get("features") if isinstance(doc, dict) else None
        if not isinstance(feats, list):
            raise TowerFileError("That GeoJSON file has no features.")
        for f in feats[:100_000]:
            if not isinstance(f, dict):
                continue
            g = f.get("geometry") or {}
            if isinstance(g, dict) and g.get("type") == "Point":
                p = f.get("properties") if isinstance(f.get("properties"), dict) else {}
                lon, lat = _point(g.get("coordinates"))
                rows.append({"ref": str(p.get("ref") or p.get("name") or p.get("id") or "")[:40],
                             "line": str(p.get("line") or p.get("line_name") or "")[:80],
                             "lon": lon, "lat": lat})
    else:
        import csv
        import io as _io
        reader = csv.DictReader(_io.StringIO(text))
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        pick = lambda *names: next((cols[n] for n in names if n in cols), None)
        c_ref, c_lat = pick("ref", "tower", "name", "id", "number"), pick("lat", "latitude", "y")
        c_lon, c_line = pick("lon", "lng", "long", "longitude", "x"), pick("line", "line_name", "feeder", "circuit")
        if not (c_lat and c_lon):
            raise TowerFileError("The CSV needs latitude and longitude columns (lat, lon), plus a tower number column (ref).")
        for r in reader:
            try:
                rows.append({"ref": (r.get(c_ref) or "").strip()[:40] if c_ref else "", "line": (r.get(c_line) or "").strip()[:80] if c_line else "",
                             "lat": float(r[c_lat]), "lon": float(r[c_lon])})
            except (TypeError, ValueError):
                continue
    rows = [r for r in rows if -90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180]  # also drops NaN
    if not rows:
        raise TowerFileError("No tower positions found in that file.")
    for r in rows:
        for k in ("ref", "line"):
            if k in r:
                r[k] = clean_text(r[k])
    return rows


def clean_text(v) -> str:
    """Tower numbers and line names come from files and OpenStreetMap: keep them plain text."""
    return re.sub(r"[<>\x00-\x1f]", "", str(v or "")).strip()


POWER_COLS = ("tower_ref", "tower_kind", "tower_dist_m", "line_name", "line_voltage_kv", "line_operator")
