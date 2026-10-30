# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Local web server: the dashboard, a small JSON API, close-ups, exports and the printable report."""
from __future__ import annotations

import hmac
import io
import ipaddress
import json
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import secrets

import segno
from flask import Flask, Response, abort, g, jsonify, render_template, request, send_from_directory

from . import __version__, exports, osm, phones
from .store import Store

# Where the phone app's web view runs. Native requests don't need CORS; these cover the web view itself.
APP_ORIGINS = {"capacitor://localhost", "ionic://localhost", "https://localhost", "http://localhost"}
LOOPBACK = ("127.0.0.1", "::1")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
CSP = ("default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class Limiter:
    """Counts failures per client address; too many in the window and the client must wait."""

    def __init__(self, limit: int, window_s: int = 600):
        self.limit, self.window = limit, window_s
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key):
        cut = time.monotonic() - self.window
        hits = [t for t in self._hits.get(key, []) if t > cut]
        self._hits[key] = hits
        return hits

    def blocked(self, key) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.limit

    def fail(self, key) -> None:
        with self._lock:
            self._recent(key).append(time.monotonic())
            if len(self._hits) > 10000:  # don't grow forever under a spray of addresses
                self._hits = {k: v for k, v in self._hits.items() if v}


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def create_app(settings, store: Store, worker=None) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024

    pairing = phones.Pairing()

    login_fails = Limiter(10)
    pair_fails = Limiter(5)
    extra_hosts = {h.strip().lower() for h in settings.allowed_hosts.split(",") if h.strip()}
    if settings.public_url:
        extra_hosts.add((urlsplit(settings.public_url).hostname or "").lower())
    dev_origins = {o.strip().rstrip("/") for o in settings.dev_origins.split(",") if o.strip()}

    def _basic_ok(auth):
        if not settings.password or auth is None or auth.type != "basic":
            return False
        # compare both, always, so timing doesn't reveal whether the username was right
        user_ok = hmac.compare_digest((auth.username or "").encode(), settings.username.encode())
        pass_ok = hmac.compare_digest((auth.password or "").encode(), settings.password.encode())
        return user_ok and pass_ok

    def _host_ok() -> bool:
        """Only answer to IP addresses, localhost and configured names. Stops DNS rebinding, where a
        web page's own name is pointed at 127.0.0.1 to reach the laptop's dashboard."""
        host = (request.host or "").lower()
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        name = name.strip("[]")
        if settings.hosted and not settings.public_url and not extra_hosts:
            return True  # hosted without a configured name: the password still protects everything
        return name == "localhost" or _is_ip(name) or name in extra_hosts

    def _own_origin(origin: str) -> bool:
        # compare host and port only: behind a TLS proxy the browser says https while we see http
        return urlsplit(origin).netloc.lower() == (request.host or "").lower()

    @app.before_request
    def require_login():
        """Who may use LineGuard:
        - the dashboard on the laptop itself, when no password is set (local mode);
        - anyone with the password (hosted mode, or a laptop with a password);
        - phones paired with a device token (sent as "Authorization: Bearer ...").
        Dashboard requests that change something must also carry the X-LineGuard header, which other
        websites can't add, so a page open in the same browser can't act on LineGuard's behalf."""
        g.device, g.who = None, "dashboard"
        if not _host_ok():
            return Response("Unknown host name. Open LineGuard by its IP address or localhost, or add the name "
                            "to allowed_hosts in config.toml.", 421, {"Content-Type": "text/plain; charset=utf-8"})
        if request.method == "OPTIONS" or request.path in ("/healthz", "/privacy"):
            return None
        client = request.remote_addr or "?"
        if request.path == "/api/pair":
            if pair_fails.blocked(client):
                return jsonify(error="Too many wrong codes. Wait a few minutes, then try again."), 429
            return None
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            dev = store.device_by_hash(phones.token_hash(header[7:].strip()))
            if dev:
                g.device, g.who = dev, dev["name"]
                if not dev["last_seen"] or dev["last_seen"][:16] != time.strftime("%Y-%m-%dT%H:%M", time.gmtime()):
                    store.touch_device(dev["id"])
                return None
            return jsonify(error="This phone is no longer paired. Pair it again from the dashboard."), 401

        # dashboard (browser) requests from here on
        origin = request.headers.get("Origin", "")
        if origin and not _own_origin(origin):
            return Response("Requests from other websites aren't accepted.", 403)
        if request.method not in SAFE_METHODS and (
                request.headers.get("X-LineGuard") != "1" or request.headers.get("Sec-Fetch-Site") == "cross-site"):
            return Response("Requests from other websites aren't accepted.", 403)
        if settings.password:
            if login_fails.blocked(client):
                return Response("Too many failed logins. Wait ten minutes, then try again.", 429)
            if _basic_ok(request.authorization):
                return None
            if request.authorization is not None:
                login_fails.fail(client)
            return Response("Log in to LineGuard.", 401, {"WWW-Authenticate": 'Basic realm="LineGuard", charset="UTF-8"'})
        if request.remote_addr in LOOPBACK:
            return None
        return Response("This LineGuard only accepts paired phones. Use the LineGuard app, or open the dashboard on the laptop itself.",
                        401, {"Content-Type": "text/plain; charset=utf-8"})

    def dashboard_only():
        if g.device is not None:
            abort(403)

    @app.after_request
    def headers(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        origin = request.headers.get("Origin", "")
        if origin in APP_ORIGINS or origin in dev_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Max-Age"] = "600"
            resp.headers["Vary"] = "Origin"
        return resp

    @app.route("/<path:_any>", methods=["OPTIONS"])
    def preflight(_any):
        return Response(status=204)

    # ---- phones
    def server_urls():
        if settings.hosted:
            return [settings.public_url.rstrip("/") if settings.public_url else request.host_url.rstrip("/")]
        urls = [f"http://{ip}:{settings.port}" for ip in phones.lan_addresses()]
        here = request.host_url.rstrip("/")
        if "127.0.0.1" not in here and "localhost" not in here and here not in urls:
            urls.insert(0, here)
        return urls

    @app.post("/api/pairing")
    def start_pairing():
        dashboard_only()
        if not settings.hosted and not settings.share:
            return jsonify(error="Phone sharing is off. Restart LineGuard with sharing on: set share = true in config.toml, or run lineguard serve --share."), 409
        code, expires = pairing.new_code()
        urls = server_urls()
        link = phones.pair_link(urls, code, settings.display_name)
        buf = io.BytesIO()
        segno.make(link, error="m").save(buf, kind="svg", scale=5, border=2, dark="#15203a")
        return jsonify(code=code, expires_in=int(expires - time.time()), urls=urls, link=link,
                       name=settings.display_name, qr=buf.getvalue().decode())

    @app.post("/api/pair")
    def pair():
        body = request.get_json(silent=True) or {}
        if not pairing.check(str(body.get("code", ""))):
            pair_fails.fail(request.remote_addr or "?")
            return jsonify(error="That code is wrong or has expired. Show a new one on the dashboard."), 403
        token = secrets.token_urlsafe(32)
        name = re.sub(r"[^\w .'-]", "", str(body.get("name") or "Phone"))[:60] or "Phone"
        store.add_device(name, phones.token_hash(token))
        return jsonify(token=token, name=settings.display_name, version=__version__, hosted=settings.hosted), 201

    @app.get("/api/devices")
    def devices():
        dashboard_only()
        return jsonify(store.devices())

    @app.delete("/api/devices/<int:did>")
    def remove_device(did):
        dashboard_only()
        store.delete_device(did)
        return jsonify(ok=True)

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    @app.get("/api/authcheck")
    def authcheck():
        """For the proxy: lets it check a login before accepting a large upload body."""
        dashboard_only()
        return Response(status=204)

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html", source_url=settings.source_url)

    def flight_or_404(fid):
        f = store.flight(fid)
        if not f:
            abort(404)
        return f

    @app.get("/")
    def index():
        return render_template("index.html", version=__version__, source_url=settings.source_url)

    @app.get("/api/status")
    def status():
        inbox = str(settings.inbox_dir)
        home = str(Path.home())
        if inbox.startswith(home + "/"):
            inbox = "~" + inbox[len(home):]
        return jsonify(version=__version__, source_url=settings.source_url, inbox=inbox, hosted=settings.hosted, name=settings.display_name,
                       share=settings.share or settings.hosted, device=g.device["name"] if g.device else None,
                       max_upload_mb=settings.max_upload_mb,
                       worker=bool(worker and worker.is_alive()),
                       dji_sdk=bool(settings.dji_irp and Path(settings.dji_irp).exists()),
                       tiles="/tiles/{z}/{x}/{y}.png" if settings.tiles_dir.is_dir() else settings.tiles_url,
                       offline_tiles=settings.tiles_dir.is_dir(),
                       standoff_m=settings.detection.standoff_m, threshold_c=settings.detection.threshold_c)

    @app.get("/api/flights")
    def flights():
        out = []
        for f in store.flights():
            f["track"] = json.loads(f["track"] or "[]")
            f["has_power"] = bool(f.pop("power", ""))
            f.pop("folder", None)
            out.append(f)
        return jsonify(out)

    @app.post("/api/flights")
    def import_flight():
        dashboard_only()
        if settings.hosted:
            return jsonify(error="On the hosted service, upload the flight instead."), 403
        raw = str((request.get_json(silent=True) or {}).get("path", "")).strip()
        if not raw:
            return jsonify(error="Give the flight folder's path."), 400
        path = Path(raw).expanduser()
        if not path.is_dir():
            return jsonify(error=f"Folder not found: {path}"), 400
        fid = store.add_flight(path.name, path.resolve())
        if worker:
            worker.wake.set()
        return jsonify(id=fid), 201

    @app.post("/api/upload")
    def upload():
        dashboard_only()
        files = request.files.getlist("files")
        if not files:
            return jsonify(error="Choose a .zip of the flight folder, or the flight's photos."), 400
        name = re.sub(r"[^A-Za-z0-9 _.-]", "", request.form.get("name", "")).strip()[:80]
        if not name:
            first = files[0].filename or "flight"
            name = PurePosixPath(first).parts[0] if "/" in first else PurePosixPath(first).stem
            name = re.sub(r"[^A-Za-z0-9 _.-]", "", name)[:80] or "flight"
        if shutil.disk_usage(settings.uploads_dir).free < MIN_FREE_BYTES + (request.content_length or 0) * 2:
            return jsonify(error="Not enough free disk space on the server for this upload."), 507
        folder = settings.uploads_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{name.replace(' ', '_')}"
        folder.mkdir(parents=True)
        try:
            saved = 0
            for f in files:
                if (f.filename or "").lower().endswith(".zip"):
                    saved += _extract_zip(f.stream, folder, settings.max_upload_mb * 2 * 1024 * 1024)
                else:
                    saved += _save_one(f, folder)
            if saved == 0:
                raise ValueError("No thermal photos in the upload (expected DJI *_T.JPG files, or .npy + .json pairs).")
        except (ValueError, zipfile.BadZipFile) as e:
            shutil.rmtree(folder, ignore_errors=True)
            return jsonify(error=str(e)), 400
        fid = store.add_flight(name, folder)
        if worker:
            worker.wake.set()
        return jsonify(id=fid, files=saved), 201

    @app.post("/api/flights/<int:fid>/reprocess")
    def reprocess(fid):
        dashboard_only()
        flight_or_404(fid)
        store.update_flight(fid, status="queued", progress=0, message="Queued")
        if worker:
            worker.wake.set()
        return jsonify(ok=True)

    @app.delete("/api/flights/<int:fid>")
    def delete(fid):
        dashboard_only()
        flight_or_404(fid)
        store.delete_flight(fid)
        return jsonify(ok=True)

    @app.get("/api/flights/<int:fid>/hotspots")
    def hotspots(fid):
        flight_or_404(fid)
        return jsonify(store.hotspots(fid))

    @app.get("/api/flights/<int:fid>/power")
    def power(fid):
        f = flight_or_404(fid)
        base = json.loads(f["power"]) if f["power"] else None
        return jsonify(osm.with_client_towers(store, base, osm.flight_points(store, fid)))

    @app.get("/api/towers")
    def tower_sources():
        return jsonify(store.tower_sources())

    @app.post("/api/towers")
    def import_towers():
        dashboard_only()
        f = request.files.get("file")
        if not f:
            return jsonify(error="Choose a CSV, KML or GeoJSON file of tower positions."), 400
        data = f.read(TOWER_FILE_MAX + 1)
        if len(data) > TOWER_FILE_MAX:
            return jsonify(error="That tower file is too large (20 MB at most)."), 400
        try:
            rows = osm.parse_towers(f.filename or "", data)
        except osm.TowerFileError as e:
            return jsonify(error=str(e)), 400
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
            return jsonify(error="Couldn't read that tower file. Use a CSV with ref, lat, lon columns, or KML or GeoJSON points."), 400
        source = re.sub(r"[^\w .-]", "", PurePosixPath(f.filename or "towers").name)[:80] or "towers"
        store.replace_towers(rows, source)
        for fl in store.flights():
            if fl["status"] == "done" and fl["hotspots"]:
                osm.attach(store, settings, fl["id"], fetch_osm=False)
        return jsonify(source=source, towers=len(rows)), 201

    @app.delete("/api/towers/<path:source>")
    def delete_towers(source):
        dashboard_only()
        store.delete_towers(source)
        for fl in store.flights():
            if fl["status"] == "done" and fl["hotspots"]:
                osm.attach(store, settings, fl["id"], fetch_osm=False)
        return jsonify(ok=True)

    @app.post("/api/flights/<int:fid>/power")
    def load_power(fid):
        dashboard_only()
        flight_or_404(fid)
        msg = osm.attach(store, settings, fid, fetch_osm=True)
        return jsonify(message=msg, ok=bool(store.flight(fid)["power"]))

    @app.patch("/api/hotspots/<int:hid>")
    def update_hotspot(hid):
        if not store.hotspot(hid):
            abort(404)
        body = request.get_json(silent=True) or {}
        try:
            applied = store.update_hotspot(hid, status=body.get("status"), note=body.get("note"),
                                           by=g.who, changed_at=body.get("changed_at"))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        h = store.hotspot(hid)
        h["applied"] = applied
        return jsonify(h), (200 if applied else 409)

    @app.get("/crops/<path:name>")
    def crops(name):
        return send_from_directory(settings.crops_dir, name, max_age=3600)

    @app.get("/tiles/<int:z>/<int:x>/<int:y>.png")
    def tiles(z, x, y):
        return send_from_directory(settings.tiles_dir, f"{z}/{x}/{y}.png", max_age=86400)

    @app.get("/qr/<int:hid>.svg")
    def qr(hid):
        h = store.hotspot(hid) or abort(404)
        buf = io.BytesIO()
        segno.make(exports.maps_link(h["lat"], h["lon"]), error="m").save(buf, kind="svg", scale=3, border=1)
        return Response(buf.getvalue(), mimetype="image/svg+xml")

    @app.get("/export/<int:fid>.<fmt>")
    def export(fid, fmt):
        f = flight_or_404(fid)
        hs = store.hotspots(fid)
        if request.args.get("open"):
            hs = [h for h in hs if h["status"] == "open"]
        kinds = {"kml": ("application/vnd.google-earth.kml+xml", exports.kml),
                 "gpx": ("application/gpx+xml", exports.gpx),
                 "csv": ("text/csv", exports.to_csv),
                 "geojson": ("application/geo+json", exports.geojson)}
        if fmt not in kinds:
            abort(404)
        mime, fn = kinds[fmt]
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in f["name"])
        return Response(fn(f, hs), mimetype=mime,
                        headers={"Content-Disposition": f'attachment; filename="lineguard_{safe}.{fmt}"'})

    @app.get("/report/<int:fid>")
    def report(fid):
        f = flight_or_404(fid)
        hs = [h for h in store.hotspots(fid) if h["status"] != "dismissed"]
        for h in hs:
            h["maps"] = exports.maps_link(h["lat"], h["lon"])
            h["where"] = osm.label(h)
            h["qr"] = segno.make(h["maps"], error="m").svg_inline(scale=2, border=0)
        counts = {s: sum(h["severity"] == s for h in hs) for s in ("major", "probable", "possible")}
        return render_template("report.html", flight=f, hotspots=hs, counts=counts, version=__version__)

    return app


ALLOWED = (".jpg", ".jpeg", ".npy", ".json", ".png")
TOWER_FILE_MAX = 20 * 1024 * 1024
MIN_FREE_BYTES = 2 * 1024 ** 3   # always leave this much disk free (the server may share its disk)


def _safe_name(raw: str) -> str | None:
    """Keep only the file's own name: no folders, no path tricks, only photo and metadata types."""
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    if not name or name.startswith(".") or not name.lower().endswith(ALLOWED):
        return None
    return name


def _save_one(f, folder: Path) -> int:
    name = _safe_name(f.filename)
    if not name:
        return 0
    f.save(folder / name)
    return 1


MAX_ZIP_ENTRIES = 20000   # a long flight is a few thousand photos, each with a few files


def _extract_zip(stream, folder: Path, limit: int) -> int:
    count, total = 0, 0
    with zipfile.ZipFile(stream) as z:
        entries = z.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ValueError(f"The zip has more than {MAX_ZIP_ENTRIES} files; that isn't a single flight.")
        for info in entries:
            if info.is_dir():
                continue
            name = _safe_name(info.filename)
            if not name:
                continue
            total += info.file_size
            if total > limit:
                raise ValueError("The zip is larger than this server accepts.")
            if shutil.disk_usage(folder).free - info.file_size < MIN_FREE_BYTES:
                raise ValueError("Not enough free disk space on the server to unpack this zip.")
            with z.open(info) as src, open(folder / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count
