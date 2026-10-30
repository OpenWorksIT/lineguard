# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""SQLite storage: flights and the hotspots found in them."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    folder TEXT NOT NULL,
    created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued, processing, done, failed
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    photos INTEGER NOT NULL DEFAULT 0,
    photos_skipped INTEGER NOT NULL DEFAULT 0,
    lines_found INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    standoff_m REAL,
    lat REAL, lon REAL,
    flown TEXT NOT NULL DEFAULT '',
    track TEXT NOT NULL DEFAULT '[]'          -- JSON list of [lat, lon] along the flight
);
CREATE TABLE IF NOT EXISTS hotspots (
    id INTEGER PRIMARY KEY,
    flight_id INTEGER NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
    lat REAL NOT NULL, lon REAL NOT NULL,
    dt REAL NOT NULL,
    severity TEXT NOT NULL,
    photos INTEGER NOT NULL,
    seen INTEGER NOT NULL,
    photo_name TEXT NOT NULL DEFAULT '',
    thermal_crop TEXT NOT NULL DEFAULT '',
    colour_crop TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',      -- open, repaired, dismissed
    note TEXT NOT NULL DEFAULT '',
    prev_id INTEGER REFERENCES hotspots(id),
    prev_dt REAL,
    updated TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS hotspots_flight ON hotspots(flight_id);
CREATE TABLE IF NOT EXISTS towers (
    id INTEGER PRIMARY KEY,
    ref TEXT NOT NULL DEFAULT '',
    line TEXT NOT NULL DEFAULT '',
    lat REAL NOT NULL, lon REAL NOT NULL,
    source TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created TEXT NOT NULL,
    last_seen TEXT NOT NULL DEFAULT ''
);
"""

MIGRATIONS = {
    "hotspots": [("updated_by", "TEXT NOT NULL DEFAULT ''"),
                 ("tower_ref", "TEXT"), ("tower_kind", "TEXT"), ("tower_dist_m", "REAL"),
                 ("line_name", "TEXT"), ("line_voltage_kv", "REAL"), ("line_operator", "TEXT")],
    "flights": [("power", "TEXT NOT NULL DEFAULT ''")],
}

STATUSES = ("open", "repaired", "dismissed")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ts(value: str) -> datetime:
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            for table, cols in MIGRATIONS.items():
                have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                for col, decl in cols:
                    if col not in have:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _write(self, sql, args=()):
        with self._lock, self._conn() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid

    def _rows(self, sql, args=()):
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    # flights
    def add_flight(self, name, folder) -> int:
        return self._write("INSERT INTO flights (name, folder, created) VALUES (?, ?, ?)", (name, str(folder), now()))

    def update_flight(self, fid, **kw):
        cols = ", ".join(f"{k} = ?" for k in kw)
        self._write(f"UPDATE flights SET {cols} WHERE id = ?", (*kw.values(), fid))

    def flights(self):
        return self._rows("""
            SELECT f.*, COUNT(h.id) AS hotspots,
                   SUM(h.severity = 'major' AND h.status = 'open') AS major_open,
                   SUM(h.status = 'open') AS open
            FROM flights f LEFT JOIN hotspots h ON h.flight_id = f.id
            GROUP BY f.id ORDER BY f.id DESC""")

    def flight(self, fid):
        rows = self._rows("SELECT * FROM flights WHERE id = ?", (fid,))
        return rows[0] if rows else None

    def folder_known(self, folder) -> bool:
        return bool(self._rows("SELECT 1 FROM flights WHERE folder = ?", (str(folder),)))

    def queued(self):
        return self._rows("SELECT * FROM flights WHERE status = 'queued' ORDER BY id")

    def reset_interrupted(self):
        self._write("UPDATE flights SET status = 'queued', progress = 0 WHERE status = 'processing'")

    def delete_flight(self, fid):
        self._write("DELETE FROM hotspots WHERE flight_id = ?", (fid,))
        self._write("DELETE FROM flights WHERE id = ?", (fid,))

    # hotspots
    def add_hotspot(self, **kw) -> int:
        kw.setdefault("updated", now())
        cols = ", ".join(kw)
        return self._write(f"INSERT INTO hotspots ({cols}) VALUES ({', '.join('?' * len(kw))})", tuple(kw.values()))

    def clear_hotspots(self, fid):
        self._write("DELETE FROM hotspots WHERE flight_id = ?", (fid,))

    def hotspots(self, fid=None):
        sql = "SELECT h.*, f.name AS flight_name, f.flown AS flight_flown FROM hotspots h JOIN flights f ON f.id = h.flight_id"
        if fid is None:
            return self._rows(sql + " ORDER BY h.dt DESC")
        return self._rows(sql + " WHERE h.flight_id = ? ORDER BY h.dt DESC", (fid,))

    def hotspot(self, hid):
        rows = self._rows("SELECT * FROM hotspots WHERE id = ?", (hid,))
        return rows[0] if rows else None

    def update_hotspot(self, hid, status=None, note=None, by="", changed_at=None):
        """Apply a change. changed_at (ISO time the change was made, e.g. on a phone that was out of
        range) lets an older change lose to a newer one. Returns False if it lost."""
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if note is not None and not isinstance(note, str):
            raise ValueError("note must be text")
        if changed_at is not None:
            if not isinstance(changed_at, str):
                raise ValueError("changed_at must be an ISO date and time")
            try:
                _ts(changed_at)
            except (TypeError, ValueError):
                raise ValueError("changed_at must be an ISO date and time") from None
            # a phone with a wrong clock (or a hostile one) can't date a change in the future
            if _ts(changed_at) > _ts(now()):
                changed_at = now()
        stamp = changed_at or now()
        cur = self.hotspot(hid)
        if changed_at and cur and cur["updated"] and _ts(cur["updated"]) > _ts(changed_at):
            return False
        if status is not None:
            self._write("UPDATE hotspots SET status = ?, updated = ?, updated_by = ? WHERE id = ?", (status, stamp, by, hid))
        if note is not None:
            self._write("UPDATE hotspots SET note = ?, updated = ?, updated_by = ? WHERE id = ?", (note[:2000], stamp, by, hid))
        return True

    def set_hotspot_power(self, hid, **cols):
        sets = ", ".join(f"{k} = ?" for k in cols)
        self._write(f"UPDATE hotspots SET {sets} WHERE id = ?", (*cols.values(), hid))

    # the client's own tower register (OpenStreetMap rarely has 33 kV collector towers)
    def replace_towers(self, rows, source):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM towers WHERE source = ?", (source,))
            c.executemany("INSERT INTO towers (ref, line, lat, lon, source) VALUES (?, ?, ?, ?, ?)",
                          [(r.get("ref", ""), r.get("line", ""), r["lat"], r["lon"], source) for r in rows])

    def towers(self, south=-90, west=-180, north=90, east=180):
        return self._rows("SELECT * FROM towers WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                          (south, north, west, east))

    def tower_sources(self):
        return self._rows("SELECT source, COUNT(*) AS towers FROM towers GROUP BY source ORDER BY source")

    def delete_towers(self, source):
        self._write("DELETE FROM towers WHERE source = ?", (source,))

    # paired phones
    def add_device(self, name, token_hash) -> int:
        return self._write("INSERT INTO devices (name, token_hash, created) VALUES (?, ?, ?)", (name[:80], token_hash, now()))

    def device_by_hash(self, token_hash):
        rows = self._rows("SELECT * FROM devices WHERE token_hash = ?", (token_hash,))
        return rows[0] if rows else None

    def devices(self):
        return self._rows("SELECT id, name, created, last_seen FROM devices ORDER BY id")

    def touch_device(self, did):
        self._write("UPDATE devices SET last_seen = ? WHERE id = ?", (now(), did))

    def delete_device(self, did):
        self._write("DELETE FROM devices WHERE id = ?", (did,))

    def earlier_hotspots(self, fid):
        return self._rows("SELECT id, lat, lon, dt FROM hotspots WHERE flight_id < ?", (fid,))
