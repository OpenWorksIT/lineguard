# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""KML, GPX, CSV and GeoJSON exports of a flight's hotspots."""
from __future__ import annotations

import csv
import io
import json
from xml.sax.saxutils import escape

SEVERITY_KML = {"major": "ff3d26d7", "probable": "ff288cf2", "possible": "ff6ac4e9"}  # aabbggrr


def maps_link(lat, lon):
    return f"https://www.google.com/maps?q={lat:.7f},{lon:.7f}"


def label(h):
    return f"LG-{h['id']}: +{h['dt']:.1f} °C ({h['severity']})"


def where(h):
    from .osm import label as tower_label
    return tower_label(h)


def kml(flight, hotspots) -> str:
    styles = "".join(
        f'<Style id="{k}"><IconStyle><color>{c}</color><scale>1.1</scale>'
        f'<Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle></Style>'
        for k, c in SEVERITY_KML.items())
    def desc(h):
        w = where(h)
        return (f"{w}. " if w else "") + "Status: {status}. Seen in {photos} of {seen} photos. {note}".format(**h)

    marks = "".join(
        f"<Placemark><name>{escape(label(h))}</name><styleUrl>#{h['severity']}</styleUrl>"
        f"<description>{escape(desc(h))}</description>"
        f"<Point><coordinates>{h['lon']:.7f},{h['lat']:.7f},0</coordinates></Point></Placemark>"
        for h in hotspots)
    return (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{escape('LineGuard: ' + flight['name'])}</name>{styles}{marks}</Document></kml>")


def gpx(flight, hotspots) -> str:
    pts = "".join(
        f'<wpt lat="{h["lat"]:.7f}" lon="{h["lon"]:.7f}"><name>{escape(label(h))}</name>'
        f"<desc>{escape(' '.join(x for x in (where(h), h['status']) if x))}</desc><sym>Flag, Red</sym></wpt>" for h in hotspots)
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="LineGuard" '
            f'xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>{escape(flight["name"])}</name></metadata>'
            f"{pts}</gpx>")


def _cell(v):
    """Stop spreadsheet programs treating text from phones or imported files as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        try:
            float(v)
            return v          # a plain number such as a negative latitude
        except ValueError:
            return "'" + v
    return v


def to_csv(flight, hotspots) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "latitude", "longitude", "temperature_rise_c", "severity", "status", "tower", "line",
                "photos", "photos_covering", "photo", "seen_before_rise_c", "note", "google_maps"])
    for h in hotspots:
        w.writerow([_cell(v) for v in [f"LG-{h['id']}", f"{h['lat']:.7f}", f"{h['lon']:.7f}", h["dt"], h["severity"], h["status"],
                    h.get("tower_ref") or "", " ".join(x for x in (h.get("line_name") or "",
                    f"{h['line_voltage_kv']:g} kV" if h.get("line_voltage_kv") else "") if x),
                    h["photos"], h["seen"], h["photo_name"], h["prev_dt"] if h["prev_dt"] is not None else "",
                    h["note"], maps_link(h["lat"], h["lon"])]])
    return buf.getvalue()


def geojson(flight, hotspots) -> str:
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
         "properties": {k: h[k] for k in ("id", "dt", "severity", "status", "photos", "seen", "note")}}
        for h in hotspots]})
