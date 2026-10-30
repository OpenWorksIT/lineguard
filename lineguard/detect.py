# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Hotspot detection from radiometric photos.

The method, per photo:
  1. find the conductors (straight lines running along the flight direction);
  2. read the temperature along each conductor and of the ground beside it;
  3. compare each conductor with the other phases at the same point, corrected
     for ground showing through thin conductors;
  4. flag anything clearly hotter than the other phases.
Then across photos:
  5. place each candidate on the ground using the photo's position and heading;
  6. keep only hotspots seen in most of the photos that covered them (glint,
     reflections and moving things appear once);
  7. grade by temperature rise (NETA similar-component bands).

Photos are expected to look straight down with the camera's "up" pointing
along the line, which is how the saved routes fly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates, median_filter, uniform_filter1d

from .geo import LocalFrame, compass_to_math

SIDE = (6, 7)  # pixels either side of a conductor used as its background


@dataclass
class View:
    """Where one photo was taken from, in local metres."""
    x: float
    y: float
    heading: float      # radians, math convention: direction the top of the image points
    depth: float        # camera to conductors, metres
    width: int
    height: int
    f: float            # focal length in pixels

    @property
    def cx(self):
        return (self.width - 1) / 2

    @property
    def cy(self):
        return (self.height - 1) / 2

    def to_world(self, u, v):
        along = -(v - self.cy) / self.f * self.depth
        across = (u - self.cx) / self.f * self.depth
        h = self.heading
        return (self.x + along * math.cos(h) + across * math.sin(h),
                self.y + along * math.sin(h) - across * math.cos(h))

    def to_pixel(self, x, y):
        h = self.heading
        dx, dy = x - self.x, y - self.y
        along = dx * math.cos(h) + dy * math.sin(h)
        across = dx * math.sin(h) - dy * math.cos(h)
        return self.cx + across / self.depth * self.f, self.cy - along / self.depth * self.f


def focal_px(width, height, diagonal_fov_deg):
    return math.hypot(width, height) / 2 / math.tan(math.radians(diagonal_fov_deg) / 2)


# --- per photo ---------------------------------------------------------------
def ridge_map(img):
    """Thin-line response: second derivative across each row, lightly smoothed along the line."""
    sm = gaussian_filter1d(img, 1.5, axis=0)
    r = np.abs(gaussian_filter1d(sm, 1.0, axis=1, order=2))
    r[:, :6] = 0
    r[:, -6:] = 0
    return r


def hough_near_vertical(edges, max_angle_deg, n_angles=49):
    """Straight lines u = a + b*v within max_angle of the image's vertical axis."""
    vs, us = np.nonzero(edges)
    h, w = edges.shape
    slopes = np.tan(np.radians(np.linspace(-max_angle_deg, max_angle_deg, n_angles)))
    pad = int(math.ceil(h * abs(slopes).max())) + 1
    acc = np.zeros((n_angles, w + 2 * pad), np.int32)
    for k, b in enumerate(slopes):
        a = np.rint(us - b * vs).astype(int) + pad
        np.add.at(acc[k], a[(a >= 0) & (a < acc.shape[1])], 1)
    peaks = []
    work = acc.copy()
    for _ in range(10):
        k, a = np.unravel_index(work.argmax(), work.shape)
        if work[k, a] < 0.25 * acc.max() or work[k, a] == 0:
            break
        peaks.append((a - pad, slopes[k]))
        work[:, max(0, a - 12):a + 13] = 0
    return peaks


def refine(r, lines):
    out = []
    h, w = r.shape
    vs = np.arange(h)
    for a, b in lines:
        u0 = a + b * vs
        cols = np.clip(np.rint(u0).astype(int)[:, None] + np.arange(-3, 4)[None, :], 0, w - 1)
        vals = r[vs[:, None], cols]
        k = np.clip(vals.argmax(axis=1), 1, 5)
        y0, y1, y2 = vals[vs, k - 1], vals[vs, k], vals[vs, k + 1]
        den = y0 - 2 * y1 + y2
        with np.errstate(divide="ignore", invalid="ignore"):
            off = np.where(np.abs(den) > 1e-6, 0.5 * (y0 - y2) / den, 0.0)
        uu = cols[vs, k] + np.clip(np.nan_to_num(off), -0.5, 0.5)
        strength = vals[vs, k]
        good = strength > np.percentile(strength, 30)
        if good.sum() < 10:
            continue
        bb, aa = np.polyfit(vs[good], uu[good], 1)
        good &= np.abs(uu - (aa + bb * vs)) < 1.0
        if good.sum() < h * 0.3:
            continue
        bb, aa = np.polyfit(vs[good], uu[good], 1)
        out.append((float(aa), float(bb), float(np.median(strength))))
    return out


def find_conductors(img, n, max_angle_deg):
    r = ridge_map(img)
    edges = r > np.percentile(r, 98.5)
    lines = refine(r, hough_near_vertical(edges, max_angle_deg))
    lines.sort(key=lambda l: -l[2])
    mid = img.shape[0] / 2
    picked = []
    for l in lines:
        if all(abs(l[0] + l[1] * mid - (p[0] + p[1] * mid)) > 15 for p in picked):
            picked.append(l)
        if len(picked) == n:
            break
    if len(picked) < n:
        return None
    picked.sort(key=lambda l: l[0] + l[1] * mid)
    return [(a, b) for a, b, _ in picked]


def sample(img, u, v):
    return map_coordinates(img, [v, u], order=1, mode="nearest")


def line_profiles(img, lines):
    vs = np.arange(img.shape[0], dtype=float)
    centre, sides = [], []
    for a, b in lines:
        u = a + b * vs
        s = np.mean([sample(img, u + sgn * k, vs) for sgn in (-1, 1) for k in SIDE], axis=0)
        trio = np.array([sample(img, u + k, vs) for k in (-1, 0, 1)])
        pick = np.abs(trio - s).argmax(axis=0)
        centre.append(trio[pick, np.arange(len(vs))])
        sides.append(s)
    return uniform_filter1d(np.array(centre), 3, axis=1), uniform_filter1d(np.array(sides), 5, axis=1)


def robust_slope(x, y):
    m = np.ones_like(x, bool)
    b = np.array([0.5, 0.0])
    for _ in range(3):
        if m.sum() < 30:
            break
        b = np.polyfit(x[m], y[m], 1)
        r = y - np.polyval(b, x)
        s = 1.4826 * np.median(np.abs(r[m] - np.median(r[m]))) + 1e-6
        m = np.abs(r - np.median(r[m])) < 3 * s
    return float(np.clip(b[0], 0, 1))


def photo_candidates(img, lines, threshold, noise_multiple):
    """Hot points in one photo: rise over the other phases at the same point."""
    centre, sides = line_profiles(img, lines)
    window = max(41, int(img.shape[0] * 0.3) | 1)
    out = []
    for p in range(len(lines)):
        others = [q for q in range(len(lines)) if q != p]
        dphase = centre[p] - centre[others].mean(axis=0)
        dside = sides[p] - sides[others].mean(axis=0)
        dcorr = dphase - robust_slope(dside, dphase) * dside
        resid = dcorr - median_filter(dcorr, size=window, mode="nearest")
        noise = 1.4826 * np.median(np.abs(resid - np.median(resid)))
        thr = max(threshold, noise_multiple * noise)
        hot = resid >= thr
        hot[:4] = hot[-4:] = False
        idx = np.flatnonzero(hot)
        if idx.size == 0:
            continue
        for run in np.split(idx, np.flatnonzero(np.diff(idx) > 2) + 1):
            k = int(run[np.argmax(resid[run])])
            a, b = lines[p]
            out.append(dict(row=k, u=float(a + b * k), dt=float(resid[k]), line=p))
    return out


# --- whole flight --------------------------------------------------------------
@dataclass
class Hotspot:
    x: float
    y: float
    lat: float
    lon: float
    dt: float
    severity: str
    photos: int
    seen: int
    best: dict                     # member nearest its photo's centre: photo index, u, v, line
    members: list = field(repr=False, default_factory=list)


@dataclass
class Result:
    hotspots: list
    rejected: int
    photos_used: int
    photos_skipped: int
    lines_found: int
    frame: LocalFrame
    views: list


def severity(dt, det):
    if dt > det.severity_major_c:
        return "major"
    if dt >= det.severity_probable_c:
        return "probable"
    return "possible"


def make_view(photo, frame, settings, shape):
    det, cam = settings.detection, settings.camera
    h, w = shape
    x, y = frame.to_xy(photo.lat, photo.lon)
    depth = det.standoff_m
    if photo.range_m and 0.6 * det.standoff_m <= photo.range_m <= 1.6 * det.standoff_m:
        depth = photo.range_m   # trust the rangefinder only when it plausibly hit the line
    return View(x, y, compass_to_math(photo.yaw_deg), depth, w, h, focal_px(w, h, cam.diagonal_fov_deg))


def analyse(photos, settings, progress=None) -> Result:
    det = settings.detection
    usable = [p for p in photos if p.pitch_deg <= det.min_nadir_pitch_deg]
    if not usable:
        raise ValueError("no straight-down photos in this flight")
    frame = LocalFrame(usable[0].lat, usable[0].lon)
    views, cands, offsets, fallback = [], [], [], []
    for i, p in enumerate(usable):
        img = p.temperatures()
        view = make_view(p, frame, settings, img.shape)
        views.append(view)
        lines = find_conductors(img, det.phases, det.max_line_angle_deg)
        if lines is None:
            fallback.append(i)
        else:
            offsets.append([(a + b * view.cy - view.cx) * view.depth / view.f for a, b in lines])
            cands += [dict(c, photo=i) for c in photo_candidates(img, lines, det.threshold_c, det.noise_multiple)]
        if progress:
            progress(i + 1, len(usable))
    # photos where the lines were unclear: use where the conductors usually sit relative to the drone
    if fallback and offsets:
        lateral = np.median(np.array(offsets), axis=0)
        for i in fallback:
            img = usable[i].temperatures()
            v = views[i]
            lines = [(v.cx + off * v.f / v.depth, 0.0) for off in lateral]
            cands += [dict(c, photo=i) for c in photo_candidates(img, lines, det.threshold_c, det.noise_multiple)]
    for c in cands:
        c["x"], c["y"] = views[c["photo"]].to_world(c["u"], c["row"])

    # confirm across photos
    hotspots, rejected = [], 0
    order = sorted(range(len(cands)), key=lambda k: -cands[k]["dt"])
    taken = np.zeros(len(cands), bool)
    xy = np.array([[c["x"], c["y"]] for c in cands]) if cands else np.zeros((0, 2))
    for k in order:
        if taken[k]:
            continue
        near = np.flatnonzero(~taken & (np.hypot(*(xy - xy[k]).T) <= det.cluster_radius_m))
        taken[near] = True
        group = [cands[j] for j in near]
        x, y = float(np.mean([g["x"] for g in group])), float(np.mean([g["y"] for g in group]))
        seen = 0
        for v in views:
            u, vv = v.to_pixel(x, y)
            if 8 <= u < v.width - 8 and 8 <= vv < v.height - 8:
                seen += 1
        n = len({g["photo"] for g in group})
        if n < det.confirm_min_photos or n < det.confirm_min_share * seen:
            rejected += 1
            continue
        dt = float(np.median([g["dt"] for g in group]))
        best = min(group, key=lambda g: math.hypot(g["u"] - views[g["photo"]].cx, g["row"] - views[g["photo"]].cy))
        lat, lon = frame.to_latlon(x, y)
        hotspots.append(Hotspot(x, y, lat, lon, dt, severity(dt, det), n, seen,
                                dict(photo=best["photo"], u=best["u"], v=best["row"], line=best["line"]), group))
    hotspots.sort(key=lambda h: -h.dt)
    return Result(hotspots, rejected, len(usable), len(photos) - len(usable),
                  len(usable) - len(fallback), frame, views)
