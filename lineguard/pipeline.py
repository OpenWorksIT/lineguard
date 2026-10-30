# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Process one flight folder: read, detect, store hotspots, cut close-ups."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import detect
from .readers import read_folder
from .store import Store

log = logging.getLogger("lineguard")

# inferno-like colour map, from cold (black/purple) to hot (yellow/white)
_STOPS = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66],
                   [245, 125, 21], [250, 193, 39], [252, 255, 164]], float)


def colourise(t: np.ndarray, lo=None, hi=None) -> Image.Image:
    lo = np.percentile(t, 1) if lo is None else lo
    hi = np.percentile(t, 99.5) if hi is None else hi
    x = np.clip((t - lo) / max(hi - lo, 1e-6), 0, 1) * (len(_STOPS) - 1)
    i = np.minimum(x.astype(int), len(_STOPS) - 2)
    f = (x - i)[..., None]
    rgb = _STOPS[i] * (1 - f) + _STOPS[i + 1] * f
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def thermal_crops(img, u, v, half=48):
    h, w = img.shape
    u0, v0 = int(np.clip(round(u) - half, 0, w - 2 * half)), int(np.clip(round(v) - half, 0, h - 2 * half))
    crop = img[v0:v0 + 2 * half, u0:u0 + 2 * half]
    close = colourise(crop).resize((6 * half, 6 * half), Image.BICUBIC)
    d = ImageDraw.Draw(close)
    cu, cv = (u - u0) * 3, (v - v0) * 3
    d.rectangle([cu - 24, cv - 30, cu + 24, cv + 30], outline=(74, 222, 128), width=3)
    ctx = colourise(img)
    ctx.thumbnail((480, 480))
    s = ctx.width / w
    d = ImageDraw.Draw(ctx)
    d.rectangle([u0 * s, v0 * s, (u0 + 2 * half) * s, (v0 + 2 * half) * s], outline=(74, 222, 128), width=2)
    return close, ctx


def colour_crop(photo, view, u, v, colour_fov, half_thermal=48):
    try:
        with Image.open(photo.colour_path, formats=["PNG", "JPEG"]) as im:
            im = im.convert("RGB")
            fc = detect.focal_px(im.width, im.height, colour_fov)
            k = fc / view.f
            cu = (im.width - 1) / 2 + (u - view.cx) * k
            cv = (im.height - 1) / 2 + (v - view.cy) * k
            r = half_thermal * k
            box = [int(cu - r), int(cv - r), int(cu + r), int(cv + r)]
            out = im.crop(box).resize((288, 288), Image.BICUBIC)
            return out
    except Exception as e:  # a missing or odd colour photo should never stop the analysis
        log.warning("colour close-up failed for %s: %s", photo.name, e)
        return None


def process(store: Store, settings, fid: int) -> None:
    flight = store.flight(fid)
    store.update_flight(fid, status="processing", progress=0, message="Reading photos")
    try:
        photos = read_folder(Path(flight["folder"]), settings)
        store.update_flight(fid, photos=len(photos), message=f"Analysing {len(photos)} photos")

        def progress(i, n):
            if i % 10 == 0 or i == n:
                store.update_flight(fid, progress=round(0.9 * i / n, 3))

        res = detect.analyse(photos, settings, progress)
        usable = [p for p in photos if p.pitch_deg <= settings.detection.min_nadir_pitch_deg]
        store.clear_hotspots(fid)
        earlier = store.earlier_hotspots(fid)
        settings.crops_dir.mkdir(parents=True, exist_ok=True)
        for n, h in enumerate(res.hotspots):
            b = h.best
            photo, view = usable[b["photo"]], res.views[b["photo"]]
            img = photo.temperatures()
            close, ctx = thermal_crops(img, b["u"], b["v"])
            stem = f"f{fid}_h{n}"
            close.save(settings.crops_dir / f"{stem}_t.png")
            ctx.save(settings.crops_dir / f"{stem}_ctx.png")
            colour = ""
            if photo.colour_path:
                cc = colour_crop(photo, view, b["u"], b["v"], settings.camera.colour_diagonal_fov_deg)
                if cc is not None:
                    cc.save(settings.crops_dir / f"{stem}_c.jpg", quality=88)
                    colour = f"{stem}_c.jpg"
            prev = _match_earlier(earlier, h.lat, h.lon, res.frame, settings.detection.history_radius_m)
            store.add_hotspot(
                flight_id=fid, lat=h.lat, lon=h.lon, dt=round(h.dt, 2), severity=h.severity,
                photos=h.photos, seen=h.seen, photo_name=photo.name,
                thermal_crop=f"{stem}_t.png", colour_crop=colour,
                prev_id=prev["id"] if prev else None, prev_dt=prev["dt"] if prev else None,
            )
        step = max(1, len(usable) // 200)
        track = [[round(p.lat, 7), round(p.lon, 7)] for p in usable[::step]]
        store.update_flight(
            fid, status="done", progress=1.0,
            message=f"{len(res.hotspots)} hotspots confirmed, {res.rejected} single-photo candidates dropped",
            photos=len(photos), photos_skipped=res.photos_skipped, lines_found=res.lines_found,
            rejected=res.rejected, standoff_m=settings.detection.standoff_m,
            lat=float(np.mean([p.lat for p in usable])), lon=float(np.mean([p.lon for p in usable])),
            flown=usable[0].taken or "", track=json.dumps(track),
        )
        log.info("flight %s done: %d hotspots", fid, len(res.hotspots))
        if res.hotspots:
            from . import osm
            log.info("flight %s: %s", fid, osm.attach(store, settings, fid, fetch_osm=settings.osm_power))
    except Exception as e:
        log.exception("flight %s failed", fid)
        store.update_flight(fid, status="failed", message=str(e)[:500])


def _match_earlier(earlier, lat, lon, frame, radius):
    best, bd = None, radius
    x, y = frame.to_xy(lat, lon)
    for e in earlier:
        ex, ey = frame.to_xy(e["lat"], e["lon"])
        d = math.hypot(ex - x, ey - y)
        if d <= bd:
            best, bd = e, d
    return best
