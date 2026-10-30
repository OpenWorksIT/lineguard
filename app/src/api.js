// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// Talking to a LineGuard server (the laptop in the vehicle or the hosted one), with an offline copy.
import { Capacitor } from '@capacitor/core';
import { http, HttpError } from './http.js';
import * as store from './db.js';

export const conn = { server: null, base: null, online: false, status: null };
const listeners = new Set();
export const onConn = (fn) => (listeners.add(fn), () => listeners.delete(fn));
const emit = () => listeners.forEach((fn) => fn(conn));

// ---- everything from a server is checked and reduced to plain values before the app uses it,
// so a wrong or hostile server can't inject markup into the screens
const num = (v, d = 0) => (Number.isFinite(Number(v)) && v !== null && v !== '' ? Number(v) : d);
const opt = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));
const str = (v, max = 200) => (v === null || v === undefined ? '' : String(v)).slice(0, max);
const oneOf = (v, set, d) => (set.includes(v) ? v : d);
const fileName = (v) => (/^[\w.-]{1,120}$/.test(String(v || '')) ? String(v) : '');
const okLatLon = (o) => Math.abs(o.lat) <= 90 && Math.abs(o.lon) <= 180;

export function cleanFlight(f) {
  return {
    id: num(f.id), name: str(f.name, 120), status: str(f.status, 20), flown: str(f.flown, 80), created: str(f.created, 40),
    hotspots: num(f.hotspots), open: num(f.open), major_open: num(f.major_open),
  };
}

export function cleanHotspot(h) {
  return {
    id: num(h.id), lat: num(h.lat), lon: num(h.lon), dt: num(h.dt),
    severity: oneOf(h.severity, ['major', 'probable', 'possible'], 'possible'),
    status: oneOf(h.status, ['open', 'repaired', 'dismissed'], 'open'),
    note: str(h.note, 2000), photos: num(h.photos), seen: num(h.seen), prev_dt: opt(h.prev_dt),
    thermal_crop: fileName(h.thermal_crop), colour_crop: fileName(h.colour_crop),
    tower_ref: str(h.tower_ref, 40), tower_kind: h.tower_kind === 'pole' ? 'pole' : 'tower', tower_dist_m: opt(h.tower_dist_m),
    line_name: str(h.line_name, 80), line_voltage_kv: opt(h.line_voltage_kv),
    updated: str(h.updated, 40), updated_by: str(h.updated_by, 60), pending: !!h.pending,
  };
}

export function cleanPower(p) {
  if (!p || typeof p !== 'object') return null;
  const arr = (a) => (Array.isArray(a) ? a.slice(0, 20000) : []);
  return {
    lines: arr(p.lines).map((l) => ({
      name: str(l.name, 80), voltage_kv: opt(l.voltage_kv),
      coords: arr(l.coords).map((c) => [num(c && c[0]), num(c && c[1])]).filter((c) => okLatLon({ lat: c[0], lon: c[1] })),
    })),
    supports: arr(p.supports).map((t) => ({ kind: t.kind === 'pole' ? 'pole' : 'tower', ref: str(t.ref, 40), lat: num(t.lat), lon: num(t.lon) })).filter(okLatLon),
  };
}

// ---- pairing
export function parsePairLink(text) {
  const raw = String(text || '').trim();
  let url;
  try { url = new URL(raw.replace(/^lineguard:\/\//, 'https://lineguard.invalid/')); } catch { return null; }
  if (!raw.startsWith('lineguard://')) return null;
  const urls = url.searchParams.getAll('u').filter(Boolean);
  const code = url.searchParams.get('c');
  if (!urls.length || !code) return null;
  return { urls, code, name: url.searchParams.get('n') || 'LineGuard' };
}

export function normaliseUrl(u) {
  let s = String(u || '').trim().replace(/\/+$/, '');
  if (!s) return '';
  if (!/^https?:\/\//i.test(s)) s = (/^[\d.]+(:\d+)?$/.test(s) ? 'http://' : 'https://') + s;
  if (/^http:\/\/[\d.]+$/.test(s)) s += ':8750';
  return s;
}

// Plain http is only for a laptop on the local Wi-Fi (an IP address or a .local name); anything on the
// internet must be https, so pairing codes and tokens never cross the internet unencrypted.
export function privateHost(hostname) {
  const h = String(hostname || '').toLowerCase().replace(/^\[|\]$/g, '');
  if (h === 'localhost' || h.endsWith('.local')) return true;
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (m) {
    const [a, b] = [Number(m[1]), Number(m[2])];
    return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
  }
  return h === '::1' || /^fe[89ab][0-9a-f]?:/.test(h) || /^f[cd][0-9a-f]{0,2}:/.test(h);
}

const isLocalHttp = (u) => {
  try { const url = new URL(u); return url.protocol === 'http:' && privateHost(url.hostname) && !url.username && !url.password; } catch { return false; }
};

export function allowedUrl(u) {
  let url;
  try { url = new URL(u); } catch { return false; }
  if (url.username || url.password) return false;
  if (url.protocol === 'https:') return true;
  return isLocalHttp(u);
}

// The addresses a pairing may use: the one the user saw, plus (for a laptop on the local Wi-Fi only)
// its other local addresses. Never an extra internet address the user wasn't shown.
export function pairingUrls(urls) {
  const all = urls.map(normaliseUrl).filter(Boolean);
  if (!all.length || !allowedUrl(all[0])) return [];
  if (!isLocalHttp(all[0])) return [all[0]];
  return [all[0], ...all.slice(1).filter((u) => isLocalHttp(u) && u !== all[0])].slice(0, 6);
}

export async function pair({ urls, code, name }, phoneName) {
  let lastErr = new Error('No address to try.');
  const tryUrls = pairingUrls(urls);
  if (!tryUrls.length) throw new Error('Use the https:// address for an online LineGuard. Plain http only works for a laptop on local Wi-Fi.');
  for (const base of tryUrls) {
    try {
      const r = await http('POST', `${base}/api/pair`, { body: { code, name: phoneName }, timeout: 5000 });
      if (!r || typeof r.token !== 'string' || r.token.length < 20) throw new Error('That address did not answer like a LineGuard.');
      const server = {
        id: (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()),
        name: str(r.name || name, 60), urls: pairingUrls([base, ...tryUrls]),
        token: r.token, hosted: !!r.hosted, added: new Date().toISOString(),
      };
      await store.saveServer(server);
      return server;
    } catch (e) {
      lastErr = e;
      if (e instanceof HttpError && e.status === 403) throw e; // wrong or expired code: no point trying others
    }
  }
  throw new Error(`Could not reach LineGuard. Check the phone is on the same Wi-Fi as the laptop. (${lastErr.message})`);
}

// ---- demo: sample data shipped with the app, so it can be tried without a LineGuard to pair with
export const DEMO = Object.freeze({ id: 'demo', name: 'Demo site', urls: ['demo'], token: '', hosted: false, demo: true });
const bundled = async (file) => {
  const r = await fetch(`demo/${file}`);
  if (!r.ok) throw new Error(`Demo data missing: ${file}`);
  return r.json();
};

// ---- connection
let timer = null;
async function probe(server) {
  for (const base of server.urls) {
    try {
      await http('GET', `${base}/healthz`, { timeout: 2500 });
      const status = await http('GET', `${base}/api/status`, { token: server.token, timeout: 4000 });
      return { base, status };
    } catch (e) {
      if (e instanceof HttpError && e.status === 401) throw e;
    }
  }
  return null;
}

export function disconnect() {
  clearInterval(timer);
  Object.assign(conn, { server: null, base: null, online: false, status: null, unpaired: false });
  emit();
}

export async function connect(server) {
  if (!server.demo) server.urls = pairingUrls(server.urls || []);
  conn.server = server;
  conn.base = null;
  conn.online = false;
  conn.status = null;
  conn.unpaired = false;
  clearInterval(timer);
  if (server.demo) {
    conn.online = true;
    emit();
    return;
  }
  emit();
  await check();
  clearInterval(timer);
  timer = setInterval(check, 20000);
}

export async function check() {
  const server = conn.server;
  if (!server || server.demo) return;
  try {
    const found = await probe(server);
    if (conn.server !== server) return;
    conn.online = !!found;
    if (found) {
      conn.base = found.base;
      conn.status = found.status;
      if (server.urls[0] !== found.base) {
        server.urls = [found.base, ...server.urls.filter((u) => u !== found.base)];
        await store.saveServer(server);
      }
      server.tiles = found.status.tiles;
      server.lastSeen = new Date().toISOString();
      await store.saveServer(server);
      await flush();
    }
  } catch (e) {
    conn.online = false;
    if (e instanceof HttpError && e.status === 401) conn.unpaired = true;
  }
  emit();
}

const sid = () => conn.server.id;
function lost() {
  if (conn.online) { conn.online = false; emit(); }
}
const api = (method, path, body) => http(method, `${conn.base}${path}`, { token: conn.server.token, body });

// ---- flights and hotspots (online: fetch and keep a copy; offline: use the copy)
export async function flights() {
  if (conn.server.demo) {
    const list = (await bundled('flights.json')).map(cleanFlight);
    for (const f of list) {
      const hs = await store.db.get(`hotspots:demo:${f.id}`);
      if (hs) {
        f.open = hs.filter((h) => h.status === 'open').length;
        f.major_open = hs.filter((h) => h.status === 'open' && h.severity === 'major').length;
      }
    }
    return { list, live: true };
  }
  if (conn.online) {
    try {
      const raw = await api('GET', '/api/flights');
      const list = (Array.isArray(raw) ? raw : []).map(cleanFlight);
      await store.db.set(`flights:${sid()}`, list);
      return { list, live: true };
    } catch { lost(); }
  }
  return { list: ((await store.db.get(`flights:${sid()}`)) || []).map(cleanFlight), live: false };
}

async function withPending(fid, hotspots) {
  const pending = (await store.outbox()).filter((c) => c.server === sid() && c.flight === fid);
  for (const c of pending) {
    const h = hotspots.find((x) => x.id === c.hid);
    if (h) {
      if (c.status !== undefined) h.status = c.status;
      if (c.note !== undefined) h.note = c.note;
      h.pending = true;
    }
  }
  return hotspots;
}

export async function flightData(fid) {
  const key = `${sid()}:${fid}`;
  if (conn.server.demo) {
    const hotspots = ((await store.db.get(`hotspots:${key}`)) || await bundled(`hotspots-${fid}.json`)).map(cleanHotspot);
    return { hotspots, power: cleanPower(await bundled(`power-${fid}.json`)), live: false, demo: true };
  }
  if (conn.online) {
    try {
      const [rawHs, rawPower] = await Promise.all([
        api('GET', `/api/flights/${fid}/hotspots`),
        api('GET', `/api/flights/${fid}/power`).catch(() => null),
      ]);
      const hotspots = (Array.isArray(rawHs) ? rawHs : []).map(cleanHotspot).filter(okLatLon);
      const power = cleanPower(rawPower);
      await store.db.set(`hotspots:${key}`, hotspots);
      if (power) await store.db.set(`power:${key}`, power);
      return { hotspots: await withPending(fid, hotspots), power, live: true };
    } catch { lost(); }
  }
  const hotspots = ((await store.db.get(`hotspots:${key}`)) || []).map(cleanHotspot);
  return { hotspots: await withPending(fid, hotspots), power: cleanPower(await store.db.get(`power:${key}`)), live: false };
}

// Close-up photos, kept on the phone so they show without signal.
const objectUrls = new Map();
export async function image(name) {
  if (!name) return null;
  if (conn.server.demo) return /^[\w.-]+\.png$/.test(name) ? `demo/crops/${name}` : null;
  const key = `${sid()}:${name}`;
  if (objectUrls.has(key)) return objectUrls.get(key);
  let blob = await store.imageCache.get(key);
  if (!blob && conn.online) {
    try {
      blob = await http('GET', `${conn.base}/crops/${encodeURIComponent(name)}`, { token: conn.server.token, blob: true });
      await store.imageCache.set(key, blob);
    } catch { return null; }
  }
  if (!blob) return null;
  const u = URL.createObjectURL(blob);
  objectUrls.set(key, u);
  return u;
}

// Download every close-up for a flight so it works offline. Reports progress.
export async function downloadImages(hotspots, progress) {
  const names = hotspots.flatMap((h) => [h.thermal_crop, h.colour_crop]).filter(Boolean);
  let done = 0;
  for (const name of names) {
    const key = `${sid()}:${name}`;
    if (!(await store.imageCache.get(key)) && conn.online) {
      try {
        const blob = await http('GET', `${conn.base}/crops/${encodeURIComponent(name)}`, { token: conn.server.token, blob: true });
        await store.imageCache.set(key, blob);
      } catch { /* keep going */ }
    }
    progress && progress(++done, names.length);
  }
  return done;
}

// ---- changes: saved on the phone first, sent when the server is in reach
export async function change(fid, h, fields) {
  const key = `${sid()}:${fid}`;
  if (conn.server.demo) {
    // Demo changes stay on the phone; there's nowhere to send them.
    Object.assign(h, fields);
    const cached = (await store.db.get(`hotspots:${key}`)) || await bundled(`hotspots-${fid}.json`);
    const c = cached.find((x) => x.id === h.id);
    if (c) Object.assign(c, fields);
    await store.db.set(`hotspots:${key}`, cached);
    return;
  }
  Object.assign(h, fields, { pending: true });
  const cached = (await store.db.get(`hotspots:${key}`)) || [];
  const c = cached.find((x) => x.id === h.id);
  if (c) Object.assign(c, fields);
  await store.db.set(`hotspots:${key}`, cached);
  await store.queueChange({ server: sid(), flight: fid, hid: h.id, ...fields, changed_at: new Date().toISOString() });
  flush();
}

let flushing = false;
export async function flush() {
  if (flushing || !conn.online || !conn.server) return;
  flushing = true;
  try {
    const list = await store.outbox();
    const keep = [];
    for (const c of list) {
      if (c.server !== sid()) { keep.push(c); continue; }
      const body = { changed_at: c.changed_at };
      if (c.status !== undefined) body.status = c.status;
      if (c.note !== undefined) body.note = c.note;
      try {
        const h = await api('PATCH', `/api/hotspots/${c.hid}`, body);
        await replaceCached(c.flight, h && cleanHotspot(h));
      } catch (e) {
        if (e instanceof HttpError && e.status === 409) await replaceCached(c.flight, e.data && cleanHotspot(e.data));
        else if (e instanceof HttpError && e.status === 404) { /* hotspot gone: drop the change */ }
        else { keep.push(c); lost(); }
      }
    }
    await store.setOutbox(keep);
  } finally {
    flushing = false;
    emit();
  }
}

async function replaceCached(fid, h) {
  if (!h || !h.id) return;
  const key = `hotspots:${sid()}:${fid}`;
  const cached = (await store.db.get(key)) || [];
  const i = cached.findIndex((x) => x.id === h.id);
  if (i >= 0) cached[i] = h;
  await store.db.set(key, cached);
}

export async function resetDemo() {
  const list = await bundled('flights.json');
  await Promise.all(list.map((f) => store.db.del(`hotspots:demo:${f.id}`)));
}

export async function pendingCount() {
  if (!conn.server || conn.server.demo) return 0;
  return (await store.outbox()).filter((c) => c.server === sid()).length;
}

// ---- map tiles: the laptop's own tiles when it has them, otherwise the online map, kept once seen
const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
export function tileTemplate() {
  const t = String((conn.status && conn.status.tiles) || (conn.server && conn.server.tiles) || OSM_TILES);
  // the laptop's own tiles (a path on the paired server), or an https tile service; nothing else
  if (/^\/tiles\/\{z\}\/\{x\}\/\{y\}\.png$/.test(t)) return { url: t, local: true };
  const ok = /^https:\/\/[^/@\s]+\/[^\s]*\{z\}[^\s]*$/.test(t) && allowedUrl(t.replace(/\{[xyz]\}/g, '0'));
  return { url: ok ? t : OSM_TILES, local: false };
}

export async function tile(z, x, y) {
  const { url, local } = tileTemplate();
  const path = url.replace('{z}', z).replace('{x}', x).replace('{y}', y);
  const key = local ? `${sid()}:${path}` : path;
  const hit = await store.tileCache.get(key);
  if (hit) return hit.blob;
  if (local && !conn.online) return null;
  const full = local ? `${conn.base}${path}` : path;
  const blob = await http('GET', full, { token: local ? conn.server.token : undefined, blob: true, timeout: 6000 });
  store.tileCache.set(key, blob);
  return blob;
}

export const isNative = () => Capacitor.isNativePlatform();
