# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Latitude/longitude to local metres and back, around a reference point.

A local tangent-plane approximation: accurate to centimetres over the few
kilometres a single flight covers. x points east, y points north.
"""
from __future__ import annotations

import math

A = 6378137.0                 # WGS84 semi-major axis
E2 = 6.69437999014e-3         # WGS84 first eccentricity squared


class LocalFrame:
    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        phi = math.radians(lat0)
        s = 1 - E2 * math.sin(phi) ** 2
        self.m_per_deg_lat = math.radians(1) * A * (1 - E2) / s ** 1.5
        self.m_per_deg_lon = math.radians(1) * A * math.cos(phi) / math.sqrt(s)

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.m_per_deg_lon, (lat - self.lat0) * self.m_per_deg_lat

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.m_per_deg_lat, self.lon0 + x / self.m_per_deg_lon


def compass_to_math(yaw_deg: float) -> float:
    """Compass heading (0 = north, clockwise) to a math angle in radians (0 = east, anticlockwise)."""
    return math.radians(90.0 - yaw_deg)
