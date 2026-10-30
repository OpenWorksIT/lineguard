# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""DJI radiometric photos (R-JPEG, e.g. DJI_..._T.JPG from a Matrice 4T).

Temperatures are decoded with dji_irp, the command-line tool in DJI's Thermal
SDK (download it from DJI; it is not redistributed here). Position and
pointing come from the photo's XMP block written by the drone.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import Photo, ReaderError

XMP_START, XMP_END = b"<x:xmpmeta", b"</x:xmpmeta>"
ATTR = re.compile(r'drone-dji:(\w+)="([^"]*)"')
ELEM = re.compile(r"<drone-dji:(\w+)>([^<]*)</drone-dji:\1>")


def parse_xmp(data: bytes) -> dict[str, str]:
    """drone-dji:* values from a JPEG's XMP block (attribute or element form)."""
    i = data.find(XMP_START)
    if i < 0:
        return {}
    j = data.find(XMP_END, i)
    text = data[i:j if j > 0 else None].decode("utf-8", "replace")
    out = dict(ATTR.findall(text))
    out.update(ELEM.findall(text))
    return out


def _f(xmp: dict, *keys):
    for k in keys:
        v = xmp.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def _exif_gps(img: Image.Image):
    gps = img.getexif().get_ifd(0x8825)
    if not gps or 2 not in gps or 4 not in gps:
        return None, None

    def dms(v, ref):
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        return -d if ref in ("S", "W") else d

    return dms(gps[2], gps.get(1, "N")), dms(gps[4], gps.get(3, "E"))


def photo_from_file(path: Path, settings) -> Photo:
    raw = path.read_bytes()[:512 * 1024]
    xmp = parse_xmp(raw)
    with Image.open(path, formats=["JPEG"]) as img:
        width, height = img.size
        taken = str(img.getexif().get(306, "") or "")
        lat = _f(xmp, "GpsLatitude")
        lon = _f(xmp, "GpsLongitude", "GpsLongtitude")  # some firmware spells it this way
        if lat is None or lon is None:
            lat, lon = _exif_gps(img)
    if lat is None or lon is None:
        raise ReaderError(f"{path.name}: no GPS position in the photo")
    yaw = _f(xmp, "GimbalYawDegree", "FlightYawDegree")
    if yaw is None:
        raise ReaderError(f"{path.name}: no camera heading in the photo")
    lrf = _f(xmp, "LRFTargetDistance")
    colour = None
    for suffix in ("_W", "_V", "_Z"):
        for ext in (".JPG", ".jpg"):
            cand = path.with_name(re.sub(r"_T$", suffix, path.stem) + ext)
            if cand.exists():
                colour = cand
                break
        if colour:
            break
    return Photo(
        name=path.stem, path=path, lat=lat, lon=lon, yaw_deg=yaw,
        pitch_deg=_f(xmp, "GimbalPitchDegree") or -90.0,
        abs_alt_m=_f(xmp, "AbsoluteAltitude"), rel_alt_m=_f(xmp, "RelativeAltitude"),
        range_m=lrf if lrf and lrf > 0 else None, taken=taken, colour_path=colour,
        width=width, height=height,
        _loader=lambda: decode(path, width, height, settings.dji_irp),
    )


def decode(path: Path, width: int, height: int, dji_irp: str) -> np.ndarray:
    if not dji_irp or not Path(dji_irp).exists():
        raise ReaderError("DJI Thermal SDK not configured: set dji_irp in config.toml to the dji_irp tool's path")
    env = dict(os.environ)
    libdir = str(Path(dji_irp).resolve().parent)
    env["LD_LIBRARY_PATH"] = libdir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "measure.raw"
        cmd = [dji_irp, "-s", str(path), "-a", "measure", "-o", str(out), "--measurefmt", "float32"]
        res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=libdir)
        if res.returncode != 0 or not out.exists():
            raise ReaderError(f"{path.name}: dji_irp failed: {(res.stderr or res.stdout).strip()[:300]}")
        temps = np.fromfile(out, dtype=np.float32)
    if temps.size != width * height:
        raise ReaderError(f"{path.name}: expected {width}x{height} temperatures, got {temps.size}")
    return temps.reshape(height, width)


def read(folder: Path, settings) -> list[Photo]:
    files = sorted(p for p in folder.rglob("*") if p.is_file() and re.search(r"_T\.jpe?g$", p.name, re.I))
    return [photo_from_file(p, settings) for p in files]
