// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// The flight map: hotspots, power lines from OpenStreetMap, and where you are.
// Tooltip text comes from servers, OpenStreetMap and imported files, so it is always passed as plain text.
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import * as api from './api.js';

const text = (t) => document.createTextNode(String(t));

export const SEV_COLOUR = { major: '#d7301f', probable: '#f07d16', possible: '#e1b012' };

// Voltage colours in the spirit of openinframap.org
function voltageColour(kv) {
  if (kv == null) return '#7a8599';
  if (kv >= 400) return '#d43ba6';
  if (kv >= 220) return '#c73030';
  if (kv >= 110) return '#2b6fd6';
  if (kv >= 50) return '#2a9d8f';
  if (kv >= 25) return '#7cae1e';
  return '#8d6e63';
}

const CachedTiles = L.GridLayer.extend({
  createTile(coords, done) {
    const img = document.createElement('img');
    img.alt = '';
    img.setAttribute('role', 'presentation');
    api.tile(coords.z, coords.x, coords.y)
      .then((blob) => {
        if (!blob) return done(new Error('no tile'), img);
        img.onload = () => { URL.revokeObjectURL(img.src); done(null, img); };
        img.src = URL.createObjectURL(blob);
      })
      .catch((e) => done(e, img));
    return img;
  },
});

export function createMap(el, { onSelect } = {}) {
  const map = L.map(el, { zoomControl: false, attributionControl: true, preferCanvas: true }).setView([-30.6, 24], 5);
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  new CachedTiles({ maxZoom: 20, maxNativeZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(map);
  const power = L.layerGroup().addTo(map);
  const spots = L.layerGroup().addTo(map);
  let me = null;
  let meAcc = null;
  const api_ = {
    map,
    setHotspots(hotspots, selectedId, fit) {
      spots.clearLayers();
      const pts = [];
      hotspots.forEach((h) => {
        const open = h.status === 'open';
        const m = L.circleMarker([h.lat, h.lon], {
          radius: h.id === selectedId ? 13 : h.severity === 'major' ? 10 : 8,
          color: h.id === selectedId ? '#15203a' : '#fff', weight: h.id === selectedId ? 4 : 2,
          fillColor: open ? SEV_COLOUR[h.severity] : h.status === 'repaired' ? '#2b8a57' : '#9aa3b5',
          fillOpacity: open ? 0.95 : 0.6,
        }).addTo(spots);
        m.bindTooltip(text(`LG-${h.id}`), { direction: 'top', offset: [0, -8] });
        m.on('click', () => onSelect && onSelect(h));
        pts.push([h.lat, h.lon]);
      });
      if (fit && pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 17 });
    },
    setPower(p) {
      power.clearLayers();
      if (!p) return;
      (p.lines || []).forEach((l) => {
        L.polyline(l.coords, { color: voltageColour(l.voltage_kv), weight: 3, opacity: 0.75 })
          .bindTooltip(text(`${l.name || 'Power line'}${Number(l.voltage_kv) ? `, ${Number(l.voltage_kv)} kV` : ''}`), { sticky: true })
          .addTo(power);
      });
      (p.supports || []).forEach((s) => {
        L.circleMarker([s.lat, s.lon], { radius: 3, color: '#3b4252', weight: 1, fillColor: '#fff', fillOpacity: 1 })
          .bindTooltip(text(`${s.kind === 'pole' ? 'Pole' : 'Tower'} ${s.ref || ''}`.trim()))
          .addTo(power);
      });
    },
    setMe(pos, follow) {
      if (!pos) return;
      const ll = [pos.lat, pos.lon];
      if (!me) {
        meAcc = L.circle(ll, { radius: pos.acc || 10, color: '#2b6fd6', weight: 1, fillOpacity: 0.08, interactive: false }).addTo(map);
        me = L.circleMarker(ll, { radius: 8, color: '#fff', weight: 3, fillColor: '#2b6fd6', fillOpacity: 1, interactive: false }).addTo(map);
      } else {
        me.setLatLng(ll);
        meAcc.setLatLng(ll).setRadius(pos.acc || 10);
      }
      if (follow) map.panTo(ll, { animate: true });
    },
    destroy() { map.remove(); },
  };
  setTimeout(() => map.invalidateSize(), 50);
  return api_;
}
