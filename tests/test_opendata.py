# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""The open data feed: history, revisits, recurring faults, file formats and data-key isolation."""
import base64
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from lineguard import config, opendata
from lineguard.store import Store

LAT, LON = -32.2850, 22.5310


@pytest.fixture()
def settings(tmp_path):
    s = config.Settings()
    s.data_dir = tmp_path / "data"
    s.inbox_dir = tmp_path / "inbox"
    s.osm_power = False
    s.camera_timezone = "Africa/Johannesburg"
    s.ensure_dirs()
    return s


def _flight(store, name, flown, points):
    fid = store.add_flight(name, f"/nowhere/{name}")
    store.update_flight(fid, status="done", flown=flown, standoff_m=20.0, lat=LAT, lon=LON, photos=len(points),
                        coverage=json.dumps(points))
    return fid


def _spot(store, fid, east_m, dt, **kw):
    lon = LON + east_m / (111320 * 0.846)
    return store.add_hotspot(flight_id=fid, lat=LAT, lon=lon, dt=dt, severity="major" if dt > 15 else "probable",
                             photos=3, seen=4, **kw)


def _history(store):
    """Three faults in June. A is repaired and comes back in September; B is repaired and stays fixed;
    C is left open and is still hot. D (far away) isn't covered by the September flight."""
    line = [[LAT, LON + i * 0.00001] for i in range(0, 120)]       # photos every ~0.9 m along 107 m
    june = _flight(store, "june", "2026:06:01 09:00:00", line + [[LAT, LON + 0.01]])
    a = _spot(store, june, 10, 22.0)
    b = _spot(store, june, 40, 6.0)
    c = _spot(store, june, 80, 9.0)
    d = _spot(store, june, 940, 5.0)                                   # only the June flight went there
    for hid, status, at in ((a, "repaired", "2026-06-10T09:00:00+02:00"), (b, "repaired", "2026-06-11T09:00:00Z")):
        # repairs are dated by the phone; LineGuard dated the hotspots when they were found (now), so back-date that
        uid = store.hotspot(hid)["uid"]
        with sqlite3.connect(store.path) as con:
            con.execute("UPDATE hotspots SET updated = '2026-06-01T08:00:00+00:00' WHERE id = ?", (hid,))
            con.execute("UPDATE hotspot_events SET at = '2026-06-01T08:00:00+00:00' WHERE hotspot_uid = ?", (uid,))
        assert store.update_hotspot(hid, status=status, note="fixed", by="Bakkie 2", changed_at=at)
    sept = _flight(store, "sept", "2026:09:01 09:00:00", line)
    a2 = _spot(store, sept, 10.3, 18.0, prev_uid=store.hotspot(a)["uid"], prev_dt=22.0)
    c2 = _spot(store, sept, 80.2, 12.5, prev_uid=store.hotspot(c)["uid"], prev_dt=9.0)
    return dict(june=june, sept=sept, a=a, b=b, c=c, d=d, a2=a2, c2=c2)


def test_history_revisits_and_recurring(settings):
    store = Store(settings.db_path)
    ids = _history(store)
    t = opendata.build(store, settings)
    uid = {k: store.hotspot(v)["uid"] for k, v in ids.items() if k not in ("june", "sept")}

    f = {r["flight_name"]: r for r in t["flights"]}
    assert f["june"]["flown_at_utc"].isoformat() == "2026-06-01T07:00:00+00:00"   # SAST is UTC+2
    assert f["june"]["flown_at_local"].isoformat() == "2026-06-01T09:00:00"

    outcome = {r["hotspot_uid"]: r for r in t["revisits"]}
    assert outcome[uid["a"]]["outcome"] == "came_back_after_repair"
    assert outcome[uid["a"]]["later_hotspot_uid"] == uid["a2"]
    assert outcome[uid["a"]]["days_repair_to_revisit"] == pytest.approx(83.0, abs=0.01)
    assert outcome[uid["b"]]["outcome"] == "repair_held" and not outcome[uid["b"]]["found_again"]
    assert outcome[uid["c"]]["outcome"] == "still_hot" and outcome[uid["c"]]["rise_change_c"] == 3.5
    assert uid["d"] not in outcome                       # the September flight never covered it
    assert len(t["revisits"]) == 3

    h = {r["hotspot_uid"]: r for r in t["hotspots"]}
    assert h[uid["a2"]]["recurring"] and h[uid["a2"]]["repairs_before"] == 1
    assert not h[uid["c2"]]["recurring"]
    assert h[uid["a2"]]["place_uid"] == uid["a"] and h[uid["a2"]]["sighting_number"] == 2
    assert not h[uid["c"]]["is_latest_sighting"] and h[uid["c2"]]["is_latest_sighting"]
    assert h[uid["a"]]["repaired_at_utc"].isoformat() == "2026-06-10T07:00:00+00:00"
    assert h[uid["a"]]["status_changed_by"] == "Bakkie 2"
    # open faults counted once per spot: C2 (C seen again) and D
    assert sorted(r["label"] for r in t["hotspots"] if r["is_open"] and r["is_latest_sighting"]) == \
        sorted([f"LG-{ids['c2']}", f"LG-{ids['d']}", f"LG-{ids['a2']}"])

    kinds = [(e["hotspot_uid"], e["kind"]) for e in t["hotspot_events"]]
    assert (uid["a"], "found") in kinds and (uid["a"], "status") in kinds and (uid["a"], "note") in kinds
    # the revisit ID is the same in every export, so a MERGE can rely on it
    assert opendata.build(store, settings)["revisits"][0]["revisit_uid"] == t["revisits"][0]["revisit_uid"]


def test_files_load_in_other_tools(settings, tmp_path):
    duckdb = pytest.importorskip("duckdb")
    store = Store(settings.db_path)
    ids = _history(store)
    store.update_hotspot(ids["c"], note="=HYPERLINK(\"http://x\")")     # a formula from a phone stays inert in CSV
    out = tmp_path / "drop"
    written = opendata.write_folder(store, settings, out)
    assert "hotspots.parquet" in written and "datapackage.json" in written

    con = duckdb.connect()
    rows = con.execute(f"SELECT outcome, count(*) FROM '{out}/revisits.parquet' GROUP BY 1 ORDER BY 1").fetchall()
    assert rows == [("came_back_after_repair", 1), ("repair_held", 1), ("still_hot", 1)]
    typ = dict(con.execute(f"DESCRIBE SELECT * FROM '{out}/hotspots.parquet'").fetchall()[i][:2]
               for i in range(len(opendata.TABLES["hotspots"]["fields"])))
    assert typ["repaired_at_utc"] == "TIMESTAMP WITH TIME ZONE" and typ["recurring"] == "BOOLEAN"
    note = con.execute(f"SELECT note FROM '{out}/hotspots.parquet' WHERE label = 'LG-{ids['c']}'").fetchone()[0]
    assert note.startswith("=HYPERLINK")                                # Parquet keeps the text as it is
    csv_note = con.execute(f"SELECT note FROM read_csv('{out}/hotspots.csv', all_varchar=true) "
                           f"WHERE label = 'LG-{ids['c']}'").fetchone()[0]
    assert csv_note.startswith("'=")
    # parquet and CSV agree
    assert con.execute(f"SELECT count(*) FROM '{out}/hotspot_events.parquet'").fetchone() == \
        con.execute(f"SELECT count(*) FROM read_csv('{out}/hotspot_events.csv')").fetchone()

    frictionless = pytest.importorskip("frictionless")
    report = frictionless.validate(str(out / "datapackage.json"))
    assert report.valid, report.flatten(["rowNumber", "fieldName", "type", "note"])

    # the guide and the Power Query files in the repo are generated from the same definitions
    import importlib.util
    spec = importlib.util.spec_from_file_location("generate", Path(__file__).parent.parent / "integrations" / "generate.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    stale = [str(path) for path, text in gen.files().items() if not path.exists() or path.read_text() != text]
    assert not stale, f"run python integrations/generate.py: {stale}"


def test_data_keys_read_the_feed_and_nothing_else(settings):
    from lineguard import phones
    from lineguard.web import create_app

    settings.hosted, settings.password = True, "a-long-dashboard-pass"
    settings.public_url = "https://lineguard.example.com"
    store = Store(settings.db_path)
    ids = _history(store)
    app = create_app(settings, store)
    web = app.test_client()
    host = {"Host": "lineguard.example.com"}
    dash = {**host, "X-LineGuard": "1",
            "Authorization": "Basic " + base64.b64encode(b"argus:a-long-dashboard-pass").decode()}

    r = web.post("/api/data-keys", json={"name": "Power BI <script>"}, headers=dash)
    assert r.status_code == 201 and r.json["key"].startswith("lgd_") and "<" not in r.json["name"]
    key = r.json["key"]
    listed = web.get("/api/data-keys", headers=dash).json
    assert listed["feed"] == "https://lineguard.example.com/api/data/v1/"
    assert set(listed["keys"][0]) == {"id", "name", "created", "last_used"}       # the key itself is never shown again
    bearer = {**host, "Authorization": f"Bearer {key}"}
    basic = {**host, "Authorization": "Basic " + base64.b64encode(f"data:{key}".encode()).decode()}

    r = web.get("/api/data/v1/hotspots.parquet", headers=bearer)
    assert r.status_code == 200 and r.data[:4] == b"PAR1"
    r = web.get("/api/data/v1/revisits.csv", headers=basic)
    assert r.status_code == 200 and r.data.decode().count("\n") == 4
    assert web.get("/api/data/v1/datapackage.json", headers=bearer).json["name"] == "lineguard-data"
    z = zipfile.ZipFile(io.BytesIO(web.get("/api/data/v1/lineguard-data.zip", headers=bearer).data))
    assert "revisits.parquet" in z.namelist()
    # the dashboard login works on the feed too (to try it in a browser)
    assert web.get("/api/data/v1/flights.csv", headers=dash).status_code == 200

    # a data key opens nothing outside the feed
    for path in ("/", "/api/flights", "/api/data-keys", "/api/devices", "/export/data.zip", "/api/authcheck",
                 f"/export/{ids['june']}.csv", f"/report/{ids['june']}"):
        assert web.get(path, headers=bearer).status_code == 401, path
        assert web.get(path, headers=basic).status_code == 401, path
    assert web.patch(f"/api/hotspots/{ids['c']}", json={"status": "dismissed"}, headers={**bearer, "X-LineGuard": "1"}).status_code == 401
    assert web.post("/api/data/v1/hotspots.csv", headers=bearer).status_code in (404, 405)
    assert web.get("/api/data/v1/devices.csv", headers=bearer).status_code == 404
    assert web.get("/api/data/v1/../devices", headers=bearer).status_code in (401, 404)
    assert web.get("/api/data/v1/hotspots.csv", headers={**bearer, "Origin": "https://evil.example"}).status_code == 403
    # a paired phone's token is not a data key
    store.add_device("Bakkie 2", phones.token_hash("phone-token"))
    assert web.get("/api/data/v1/hotspots.csv", headers={**host, "Authorization": "Bearer phone-token"}).status_code == 401
    # no key, wrong key, then too many wrong keys
    assert web.get("/api/data/v1/hotspots.csv", headers=host).status_code == 401
    for _ in range(9):
        assert web.get("/api/data/v1/hotspots.csv", headers={**host, "Authorization": "Bearer lgd_wrong"}).status_code == 401
    assert web.get("/api/data/v1/hotspots.csv", headers=bearer).status_code == 429

    # removing the key cuts the tool off (new app: fresh rate limiter)
    web2 = create_app(settings, store).test_client()
    kid = web2.get("/api/data-keys", headers=dash).json["keys"][0]["id"]
    assert web2.get("/api/data/v1/hotspots.csv", headers=bearer).status_code == 200
    assert web2.delete(f"/api/data-keys/{kid}", headers=dash).status_code == 200
    assert web2.get("/api/data/v1/hotspots.csv", headers=bearer).status_code == 401
    # a phone can't make data keys
    assert web2.post("/api/data-keys", json={"name": "x"},
                     headers={**host, "Authorization": "Bearer phone-token"}).status_code == 403


def test_old_database_gets_ids_and_history(settings, tmp_path):
    """A database from LineGuard 0.3 (no IDs, no history) is upgraded in place on start."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE flights (id INTEGER PRIMARY KEY, name TEXT NOT NULL, folder TEXT NOT NULL, created TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
            photos INTEGER NOT NULL DEFAULT 0, photos_skipped INTEGER NOT NULL DEFAULT 0, lines_found INTEGER NOT NULL DEFAULT 0,
            rejected INTEGER NOT NULL DEFAULT 0, standoff_m REAL, lat REAL, lon REAL, flown TEXT NOT NULL DEFAULT '',
            track TEXT NOT NULL DEFAULT '[]', power TEXT NOT NULL DEFAULT '');
        CREATE TABLE hotspots (id INTEGER PRIMARY KEY, flight_id INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
            dt REAL NOT NULL, severity TEXT NOT NULL, photos INTEGER NOT NULL, seen INTEGER NOT NULL,
            photo_name TEXT NOT NULL DEFAULT '', thermal_crop TEXT NOT NULL DEFAULT '', colour_crop TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open', note TEXT NOT NULL DEFAULT '', prev_id INTEGER, prev_dt REAL,
            updated TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '');
        INSERT INTO flights (id, name, folder, created, status, flown, track) VALUES
            (1, 'old', '/x', '2026-05-01T08:00:00+00:00', 'done', '2026:05:01 09:00:00', '[[-32.285, 22.531]]');
        INSERT INTO hotspots (id, flight_id, lat, lon, dt, severity, photos, seen, status, note, updated, updated_by) VALUES
            (1, 1, -32.285, 22.531, 7.0, 'probable', 2, 3, 'repaired', 'done', '2026-05-03T10:00:00+00:00', 'Bakkie 1'),
            (2, 1, -32.285, 22.5312, 3.5, 'possible', 2, 2, 'open', '', '2026-05-01T08:00:00+00:00', '');
        UPDATE hotspots SET prev_id = 1 WHERE id = 2;
    """)
    con.commit()
    con.close()
    store = Store(db)
    assert store.site_id and all(h["uid"] for h in store.hotspots())
    assert store.hotspot(2)["prev_uid"] == store.hotspot(1)["uid"]
    t = opendata.build(store, settings)
    h = {r["label"]: r for r in t["hotspots"]}
    assert h["LG-1"]["repaired_at_utc"].isoformat() == "2026-05-03T10:00:00+00:00"
    assert [e["kind"] for e in t["hotspot_events"]] == ["found", "status", "found"]
    Store(db)                                   # starting again changes nothing
    assert len(opendata.build(store, settings)["hotspot_events"]) == 3
