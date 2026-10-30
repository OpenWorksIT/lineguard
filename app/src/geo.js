// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// Distances, bearings and the order to visit hotspots in.
const R = 6371008.8;
const rad = (d) => (d * Math.PI) / 180;
const deg = (r) => (r * 180) / Math.PI;

export function distance(a, b) {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function bearing(a, b) {
  const y = Math.sin(rad(b.lon - a.lon)) * Math.cos(rad(b.lat));
  const x = Math.cos(rad(a.lat)) * Math.sin(rad(b.lat)) - Math.sin(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.cos(rad(b.lon - a.lon));
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

const POINTS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];
const SHORT = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
export const compassWord = (b) => POINTS[Math.round(b / 45) % 8];
export const compassShort = (b) => SHORT[Math.round(b / 45) % 8];

export function fmtDistance(m) {
  if (m < 50) return `${Math.round(m)} m`;
  if (m < 1000) return `${Math.round(m / 10) * 10} m`;
  if (m < 10000) return `${(m / 1000).toFixed(1)} km`;
  return `${Math.round(m / 1000)} km`;
}

export function spokenDistance(m) {
  if (m < 1000) return `${Math.round(m / 50) * 50 || Math.round(m)} metres`;
  const km = m / 1000;
  return `${km < 10 ? km.toFixed(1).replace(/\.0$/, '') : Math.round(km)} kilometres`;
}

const SEV_RANK = { major: 0, probable: 1, possible: 2 };

// Nearest-neighbour tour from where you are. "major first" visits every major fault before the rest.
export function plan(from, hotspots, { majorFirst = false } = {}) {
  const groups = majorFirst
    ? [hotspots.filter((h) => h.severity === 'major'), hotspots.filter((h) => h.severity !== 'major')]
    : [hotspots.slice()];
  const out = [];
  let here = from;
  for (const g of groups) {
    const left = g.slice();
    while (left.length) {
      let best = 0;
      if (here) {
        let bd = Infinity;
        left.forEach((h, i) => {
          const d = distance(here, h);
          if (d < bd) { bd = d; best = i; }
        });
      } else {
        left.sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity] || b.dt - a.dt);
      }
      const next = left.splice(best, 1)[0];
      out.push(next);
      here = next;
    }
  }
  return out;
}
