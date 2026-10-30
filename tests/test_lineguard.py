# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from lineguard import config, demo, detect, exports
from lineguard.geo import LocalFrame
from lineguard.pipeline import process
from lineguard.readers import read_folder
from lineguard.readers.dji import parse_xmp
from lineguard.store import Store


@pytest.fixture(scope="module")
def flight(tmp_path_factory):
    folder = tmp_path_factory.mktemp("flight")
    truth = demo.make_flight(folder, "33kv_mild", seed=3, spans=2)
    return folder, truth


@pytest.fixture()
def settings(tmp_path):
    s = config.Settings()
    s.data_dir = tmp_path / "data"
    s.inbox_dir = tmp_path / "inbox"
    s.osm_power = False          # no network in tests
    s.ensure_dirs()
    return s



def dashboard(app):
    """A test client that behaves like the dashboard page (sends the X-LineGuard header)."""
    c = app.test_client()
    c.environ_base["HTTP_X_LINEGUARD"] = "1"
    return c

def test_geo_round_trip():
    f = LocalFrame(-32.28, 22.53)
    lat, lon = f.to_latlon(*f.to_xy(-32.2812345, 22.5398765))
    assert lat == pytest.approx(-32.2812345, abs=1e-9)
    assert lon == pytest.approx(22.5398765, abs=1e-9)
    x, y = f.to_xy(-32.28, 22.53 + 0.001)
    assert 93 < x < 95 and abs(y) < 1e-6   # about 94 m per 0.001 degree of longitude at this latitude


def test_view_round_trip():
    v = detect.View(10, 20, math.radians(33), 20, 640, 512, detect.focal_px(640, 512, 45))
    x, y = v.to_world(400, 100)
    u, vv = v.to_pixel(x, y)
    assert (u, vv) == pytest.approx((400, 100))


def test_parse_xmp_both_forms():
    attr = b'<x:xmpmeta><rdf:Description drone-dji:GpsLatitude="-32.1" drone-dji:GpsLongtitude="22.5" drone-dji:GimbalYawDegree="+61.2"/></x:xmpmeta>'
    elem = b"<x:xmpmeta><drone-dji:LRFTargetDistance>19.8</drone-dji:LRFTargetDistance></x:xmpmeta>"
    assert parse_xmp(attr) == {"GpsLatitude": "-32.1", "GpsLongtitude": "22.5", "GimbalYawDegree": "+61.2"}
    assert parse_xmp(elem)["LRFTargetDistance"] == "19.8"


def test_detection_finds_planted_faults(flight, settings):
    folder, truth = flight
    res = detect.analyse(read_folder(folder, settings), settings)
    frame = LocalFrame(*demo.BASE)
    big = [f for f in truth["faults"] if f["dt"] >= 6]
    found, errors = 0, []
    for f in big:
        fx, fy = frame.to_xy(f["lat"], f["lon"])
        d = min(math.hypot(*np.subtract(frame.to_xy(h.lat, h.lon), (fx, fy))) for h in res.hotspots)
        if d <= 1.0:
            found += 1
            errors.append(d)
    assert found >= 0.85 * len(big)
    assert max(errors) < 0.6


def test_pipeline_store_and_exports(flight, settings):
    folder, _ = flight
    store = Store(settings.db_path)
    fid = store.add_flight("test", folder)
    process(store, settings, fid)
    f = store.flight(fid)
    assert f["status"] == "done", f["message"]
    hs = store.hotspots(fid)
    assert hs and all((settings.crops_dir / h["thermal_crop"]).exists() for h in hs)
    store.update_hotspot(hs[0]["id"], status="repaired", note="re-torqued clamp")
    assert store.hotspot(hs[0]["id"])["status"] == "repaired"
    assert "<Placemark>" in exports.kml(f, hs)
    assert "<wpt" in exports.gpx(f, hs)
    assert exports.to_csv(f, hs).count("\n") == len(hs) + 1
    assert len(json.loads(exports.geojson(f, hs))["features"]) == len(hs)
    # a second flight over the same line links its hotspots to the first
    fid2 = store.add_flight("again", folder)
    process(store, settings, fid2)
    assert any(h["prev_id"] for h in store.hotspots(fid2))


def test_web_api(flight, settings):
    from lineguard.web import create_app
    folder, _ = flight
    store = Store(settings.db_path)
    fid = store.add_flight("web", folder)
    process(store, settings, fid)
    client = dashboard(create_app(settings, store))
    assert client.get("/").status_code == 200
    assert client.get("/api/flights").json[0]["status"] == "done"
    hs = client.get(f"/api/flights/{fid}/hotspots").json
    r = client.patch(f"/api/hotspots/{hs[0]['id']}", json={"status": "dismissed"})
    assert r.json["status"] == "dismissed"
    assert client.patch(f"/api/hotspots/{hs[0]['id']}", json={"status": "nope"}).status_code == 400
    assert client.get(f"/qr/{hs[0]['id']}.svg").data.startswith(b"<?xml")
    assert client.get(f"/report/{fid}").status_code == 200
    assert client.get(f"/export/{fid}.kml").status_code == 200
    assert client.post("/api/flights", json={"path": "/no/such/folder"}).status_code == 400


def test_hosted_login_and_upload(flight, settings, tmp_path):
    import io
    import zipfile

    from lineguard.web import create_app
    folder, _ = flight
    settings.hosted, settings.username, settings.password = True, "argus", "s3cret"
    store = Store(settings.db_path)
    client = dashboard(create_app(settings, store))
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("argus", "wrong")).status_code == 401
    auth = ("argus", "s3cret")
    assert client.get("/", auth=auth).status_code == 200
    # local folder import is off on a server
    assert client.post("/api/flights", json={"path": str(folder)}, auth=auth).status_code == 403
    # a zip with a few photos, plus entries that must be ignored
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in sorted(folder.glob("DEMO_000*"))[:6]:
            z.write(p, f"DCIM/100MEDIA/{p.name}")
        z.writestr("../../escape.json", "{}")
        z.writestr("run.sh", "echo no")
    buf.seek(0)
    r = client.post("/api/upload", data={"files": (buf, "flight.zip"), "name": "Line A"},
                    content_type="multipart/form-data", auth=auth)
    assert r.status_code == 201, r.json
    up = store.flight(r.json["id"])
    names = sorted(p.name for p in Path(up["folder"]).iterdir())
    # the "../../" entry is flattened into the upload folder, never written outside it
    assert len(names) == 7 and "run.sh" not in names
    assert not (Path(up["folder"]).parent.parent / "escape.json").exists()
    assert Path(up["folder"]).parent == settings.uploads_dir
    bad = client.post("/api/upload", data={"files": (io.BytesIO(b"x"), "notes.txt")},
                      content_type="multipart/form-data", auth=auth)
    assert bad.status_code == 400


def test_phone_pairing_and_tokens(flight, settings):
    from lineguard.web import create_app
    folder, _ = flight
    settings.share = True
    store = Store(settings.db_path)
    fid = store.add_flight("pair", folder)
    process(store, settings, fid)
    c = dashboard(create_app(settings, store))
    phone = {"REMOTE_ADDR": "10.42.0.57"}
    # a phone on the Wi-Fi can't get in without pairing
    assert c.get("/api/flights", environ_base=phone).status_code == 401
    # the laptop (loopback) starts pairing and gets a code + QR
    p = c.post("/api/pairing").json
    assert len(p["code"]) == 6 and p["link"].startswith("lineguard://pair?c=") and "<svg" in p["qr"]
    assert c.post("/api/pair", json={"code": "000000" if p["code"] != "000000" else "111111"}, environ_base=phone).status_code == 403
    r = c.post("/api/pair", json={"code": p["code"], "name": "Jan's phone"}, environ_base=phone)
    assert r.status_code == 201
    token = r.json["token"]
    # the code works once only
    assert c.post("/api/pair", json={"code": p["code"]}, environ_base=phone).status_code == 403
    auth = {"Authorization": f"Bearer {token}"}
    assert c.get("/api/flights", headers=auth, environ_base=phone).status_code == 200
    hs = c.get(f"/api/flights/{fid}/hotspots", headers=auth, environ_base=phone).json
    crop = c.get(f"/crops/{hs[0]['thermal_crop']}", headers=auth, environ_base=phone)
    assert crop.status_code == 200 and crop.mimetype == "image/png"
    # a phone can't delete flights or create pairings
    assert c.delete(f"/api/flights/{fid}", headers=auth, environ_base=phone).status_code == 403
    assert c.post("/api/pairing", headers=auth, environ_base=phone).status_code == 403
    # status changes record who made them; an older offline change loses to a newer one
    # (a change dated in the future is treated as made now, so one phone's clock can't lock others out)
    r = c.patch(f"/api/hotspots/{hs[0]['id']}", json={"status": "repaired", "changed_at": "2099-01-01T10:00:00+00:00"},
                headers=auth, environ_base=phone)
    assert r.status_code == 200 and r.json["updated_by"] == "Jan's phone" and r.json["updated"] < "2099"
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = c.patch(f"/api/hotspots/{hs[0]['id']}", json={"status": "open", "changed_at": old},
                headers=auth, environ_base=phone)
    assert r.status_code == 409 and r.json["status"] == "repaired"
    assert c.patch(f"/api/hotspots/{hs[0]['id']}", json={"note": 123}, headers=auth, environ_base=phone).status_code == 400
    assert c.patch(f"/api/hotspots/{hs[0]['id']}", json={"changed_at": 5}, headers=auth, environ_base=phone).status_code == 400
    # CORS for the app's own origin only
    r = c.get("/api/status", headers={**auth, "Origin": "capacitor://localhost"}, environ_base=phone)
    assert r.headers["Access-Control-Allow-Origin"] == "capacitor://localhost"
    r = c.get("/api/status", headers={**auth, "Origin": "https://evil.example"}, environ_base=phone)
    assert "Access-Control-Allow-Origin" not in r.headers
    # revoking the phone locks it out
    did = c.get("/api/devices").json[0]["id"]
    c.delete(f"/api/devices/{did}")
    assert c.get("/api/flights", headers=auth, environ_base=phone).status_code == 401


def test_osm_power_labels():
    from lineguard import osm
    raw = {"elements": [
        {"type": "way", "id": 1, "tags": {"power": "line", "name": "Kappa", "voltage": "132000;33000", "operator": "Eskom"},
         "geometry": [{"lat": -32.0, "lon": 22.0}, {"lat": -32.0, "lon": 22.01}]},
        {"type": "node", "id": 2, "lat": -32.0, "lon": 22.0050, "tags": {"power": "tower", "ref": "47"}},
        {"type": "node", "id": 3, "lat": -32.0, "lon": 22.0090, "tags": {"power": "tower", "ref": "48"}},
        {"type": "way", "id": 4, "tags": {"power": "substation", "name": "Gamma"},
         "geometry": [{"lat": -32.01, "lon": 22.0}, {"lat": -32.011, "lon": 22.001}]},
    ]}
    power = osm.simplify(raw)
    assert power["lines"][0]["voltage_kv"] == 132 and len(power["supports"]) == 2 and power["areas"][0]["name"] == "Gamma"
    n = osm.nearest(power, -32.0, 22.00505)          # ~5 m east of tower 47
    assert n["tower_ref"] == "47" and n["tower_dist_m"] < 10 and n["line_name"] == "Kappa"
    assert osm.label(n) == "Tower 47, Kappa 132 kV line"
    assert osm.nearest(power, -32.02, 22.0) == {}       # 2 km away: nothing
    q = osm.query(*osm.bbox_around([[-32.0, 22.0]]))
    assert q.startswith("[out:json]") and 'power"~"^(line|minor_line|cable)$' in q


def test_security_guards(tmp_path):
    """Host names, cross-site requests, rate limits, headers and hostile uploads."""
    from lineguard.web import create_app
    settings = config.Settings(data_dir=tmp_path / "data", inbox_dir=tmp_path / "inbox", share=True)
    settings.osm_power = False
    settings.ensure_dirs()
    app = create_app(settings, Store(settings.db_path))
    c = app.test_client()
    # DNS rebinding: a foreign host name is refused, IP addresses and localhost are fine
    assert c.get("/api/status", headers={"Host": "rebind.attacker.example:8750"}).status_code == 421
    assert c.get("/api/status", headers={"Host": "127.0.0.1:8750"}).status_code == 200
    assert c.get("/api/status", headers={"Host": "localhost:8750"}).status_code == 200
    # cross-site changes: no X-LineGuard header, or a foreign Origin, is refused
    assert c.post("/api/pairing").status_code == 403
    assert c.post("/api/pairing", headers={"X-LineGuard": "1", "Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/flights", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/pairing", headers={"X-LineGuard": "1", "Sec-Fetch-Site": "cross-site"}).status_code == 403
    ok = c.post("/api/pairing", headers={"X-LineGuard": "1", "Origin": "http://localhost"})
    assert ok.status_code == 200
    assert c.post("/api/flights", json={}, headers={"X-LineGuard": "1"}).status_code == 400  # empty path
    # security headers, and CORS only for the app's own origins
    r = c.get("/", headers={"Origin": "http://localhost"})
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"] and r.headers["X-Frame-Options"] == "DENY"
    phone = {"REMOTE_ADDR": "10.42.0.50"}
    assert "Access-Control-Allow-Origin" not in c.get("/healthz", headers={"Origin": "http://localhost:3000"}).headers
    assert c.get("/healthz", headers={"Origin": "capacitor://localhost"}).headers["Access-Control-Allow-Origin"] == "capacitor://localhost"
    # pairing: wrong codes from one address are limited without blocking the server
    for _ in range(5):
        assert c.post("/api/pair", json={"code": "000001"}, environ_base=phone).status_code == 403
    assert c.post("/api/pair", json={"code": ok.json["code"]}, environ_base=phone).status_code == 429
    assert c.post("/api/pair", json={"code": ok.json["code"]}, environ_base={"REMOTE_ADDR": "10.42.0.51"}).status_code == 201
    # tower names can't carry markup; KML is read in one pass
    from lineguard import osm
    rows = osm.parse_towers("t.csv", b"ref,lat,lon\n<img src=x onerror=alert(1)>,-32.1,22.5\n")
    assert "<" not in rows[0]["ref"]
    import time as _time
    t0 = _time.monotonic()
    osm.parse_towers("bomb.kml", b"<Placemark>" * 50000 + b"<Placemark><name>T1</name><Point><coordinates>22.5,-32.1</coordinates></Point></Placemark>")
    assert _time.monotonic() - t0 < 2
    # CSV export can't smuggle spreadsheet formulas
    assert exports._cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and exports._cell("T41") == "T41"
    # a .npy declaring a huge array is refused before any memory is allocated
    from lineguard.readers.generic import _load
    bad = tmp_path / "huge.npy"
    with open(bad, "wb") as fh:
        np.lib.format.write_array_header_1_0(fh, {"descr": "<f4", "fortran_order": False, "shape": (200000, 200000)})
    with pytest.raises(ValueError):
        _load(bad)


def test_hosted_password_rules(tmp_path, monkeypatch):
    for var, val in (("LINEGUARD_HOSTED", "1"), ("LINEGUARD_DATA_DIR", str(tmp_path))):
        monkeypatch.setenv(var, val)
    monkeypatch.setenv("LINEGUARD_PASSWORD", "change-me-to-something-long")
    with pytest.raises(SystemExit):
        config.load(tmp_path / "none.toml")
    monkeypatch.setenv("LINEGUARD_PASSWORD", "short")
    with pytest.raises(SystemExit):
        config.load(tmp_path / "none.toml")
    monkeypatch.setenv("LINEGUARD_PASSWORD", "a-proper-long-password")
    monkeypatch.setenv("LINEGUARD_PUBLIC_URL", "https://lineguard.example.com")
    s = config.load(tmp_path / "none.toml")
    from lineguard.web import create_app
    s.ensure_dirs()
    c = create_app(s, Store(s.db_path)).test_client()
    c.environ_base["HTTP_X_LINEGUARD"] = "1"
    good = {"Authorization": "Basic " + __import__("base64").b64encode(b"argus:a-proper-long-password").decode(),
            "Host": "lineguard.example.com"}
    p = c.post("/api/pairing", headers=good)
    assert p.status_code == 200 and "https%3A%2F%2Flineguard.example.com" in p.json["link"]
    bad = {"Authorization": "Basic " + __import__("base64").b64encode(b"argus:wrong").decode(), "Host": "lineguard.example.com"}
    codes = [c.get("/api/status", headers=bad).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_pentest_round_two(tmp_path, monkeypatch):
    """Fixes from the second penetration test."""
    import base64
    import io
    import zipfile
    from lineguard import osm, phones
    from lineguard.web import create_app, MAX_ZIP_ENTRIES
    # pairing: wrong guesses from other addresses don't void the code for the real phone
    pairing = phones.Pairing()
    code, _ = pairing.new_code()
    for _ in range(20):
        assert not pairing.check("000000" if code != "000000" else "111111")
    assert pairing.check(code)
    # tower files: malformed GeoJSON gives a clean 400-style error, never a crash or a Python message
    for bad in (b'{"features":[{"geometry":{"type":"Point"}}]}', b'{"features":[{"geometry":{"type":"Point","coordinates":[1.0]}}]}',
                b'{"features":' + b"[" * 20000 + b"]" * 20000 + b"}", b'{"features":[{"geometry":{"type":"Point","coordinates":["n","x"]}}]}',
                b"[]", b'{"features": 5}'):
        with pytest.raises(osm.TowerFileError):
            osm.parse_towers("t.geojson", bad)
    # CSV keeps negative coordinates as numbers
    assert exports._cell("-32.2850000") == "-32.2850000" and exports._cell("-cmd") == "'-cmd"
    # OSM replies with missing fields are skipped, not fatal
    assert osm.simplify({"elements": [None, {"type": "node", "tags": {"power": "tower"}}, {"type": "way", "tags": {"power": "line"}, "geometry": [{"lat": 1}]}]})["supports"] == []
    # hosted mode: needs a public URL; behind a proxy, limits apply per client, not to the proxy
    monkeypatch.setenv("LINEGUARD_HOSTED", "1")
    monkeypatch.setenv("LINEGUARD_DATA_DIR", str(tmp_path / "h"))
    monkeypatch.setenv("LINEGUARD_PASSWORD", "a-proper-long-password")
    with pytest.raises(SystemExit):
        config.load(tmp_path / "none.toml")
    monkeypatch.setenv("LINEGUARD_PUBLIC_URL", "https://lineguard.example.com")
    monkeypatch.setenv("LINEGUARD_BEHIND_PROXY", "1")
    s = config.load(tmp_path / "none.toml")
    s.ensure_dirs()
    app = create_app(s, Store(s.db_path))
    c = app.test_client()   # (waitress puts the client's address from X-Forwarded-For into REMOTE_ADDR)
    host = {"Host": "lineguard.example.com"}
    good = {**host, "Authorization": "Basic " + base64.b64encode(b"argus:a-proper-long-password").decode()}
    bad = {**host, "Authorization": "Basic " + base64.b64encode(b"argus:wrong").decode()}
    for _ in range(12):
        c.get("/api/status", headers={**bad, "X-Forwarded-For": "203.0.113.9"}, environ_base={"REMOTE_ADDR": "203.0.113.9"})
    assert c.get("/api/status", headers={**bad, "X-Forwarded-For": "203.0.113.9"}, environ_base={"REMOTE_ADDR": "203.0.113.9"}).status_code == 429
    assert c.get("/api/status", headers=good, environ_base={"REMOTE_ADDR": "198.51.100.7"}).status_code == 200
    # the proxy's login check before big uploads
    assert c.get("/api/authcheck", headers=good, environ_base={"REMOTE_ADDR": "198.51.100.7"}).status_code == 204
    assert c.get("/api/authcheck", headers=host, environ_base={"REMOTE_ADDR": "198.51.100.8"}).status_code == 401
    # zips with absurd numbers of entries are refused before anything is written
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(MAX_ZIP_ENTRIES + 1):
            z.writestr(f"f{i}.json", "")
    buf.seek(0)
    r = c.post("/api/upload", data={"files": (buf, "many.zip")}, headers={**good, "X-LineGuard": "1"}, environ_base={"REMOTE_ADDR": "198.51.100.7"},
               content_type="multipart/form-data")
    assert r.status_code == 400 and "more than" in r.json["error"]
    # phones can't trigger OpenStreetMap fetches
    import secrets as _s
    store = Store(s.db_path)
    tok = _s.token_urlsafe(32)
    store.add_device("p", phones.token_hash(tok))
    assert c.post("/api/flights/1/power", headers={**host, "Authorization": f"Bearer {tok}"}).status_code == 403
