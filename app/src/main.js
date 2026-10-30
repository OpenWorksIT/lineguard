// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// LineGuard field app: pair with a LineGuard, take a flight offline, and drive to each hotspot.
import './style.css';
import { Capacitor } from '@capacitor/core';
import { App } from '@capacitor/app';
import { Preferences } from '@capacitor/preferences';
import * as api from './api.js';
import * as store from './db.js';
import * as dev from './device.js';
import { createMap, SEV_COLOUR } from './map.js';
import { bearing, distance, plan, fmtDistance, spokenDistance, compassWord, compassShort } from './geo.js';

const $app = document.getElementById('app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const SEV = { major: 'Major', probable: 'Probable', possible: 'Possible' };
const STATUS = { open: 'Open', repaired: 'Repaired', dismissed: 'Not a fault' };
const PRIVACY_URL = 'https://lineguard.openworks.co.za/privacy';
const SOURCE_URL = 'https://github.com/OpenWorksIT/lineguard';

const S = {
  screen: 'servers', back: [], flight: null, hotspots: [], power: null, selected: null, tab: 'map',
  pairPrefill: null, settings: { voice: true, majorFirst: false, mapsApp: 'google', arrival: 35 },
};
let map = null;
let cleanup = [];

async function loadSettings() {
  try {
    const { value } = await Preferences.get({ key: 'settings' });
    if (value) Object.assign(S.settings, JSON.parse(value));
  } catch { /* defaults */ }
}
const saveSettings = () => Preferences.set({ key: 'settings', value: JSON.stringify(S.settings) });

function go(screen, push = true) {
  if (push && S.screen !== screen) S.back.push(S.screen);
  S.screen = screen;
  render();
}
function back() {
  if (S.screen === 'drive') stopDrive();
  const prev = S.back.pop();
  if (prev) { S.screen = prev; render(); return true; }
  return false;
}

function tearDown() {
  cleanup.forEach((fn) => fn());
  cleanup = [];
  if (map) { map.destroy(); map = null; }
}

function render() {
  tearDown();
  document.body.dataset.screen = S.screen;
  ({ servers: renderServers, pair: renderPair, flights: renderFlights, flight: renderFlight,
     hotspot: renderHotspot, drive: renderDrive, settings: renderSettings })[S.screen]();
}

function topBar(title, { backBtn = true, right = '' } = {}) {
  const c = api.conn;
  const dot = !c.server ? '' : c.server.demo ? '<span class="link demo">Demo</span>' : c.online
    ? `<span class="link on" title="Connected to ${esc(c.server.name)}">Connected</span>`
    : `<span class="link off" title="Using the copy on this phone">Offline</span>`;
  return `<header class="bar">
    ${backBtn ? '<button class="icon" data-act="back" aria-label="Back">‹</button>' : '<img class="mark" src="logo-mark.svg" alt="">'}
    <h1>${esc(title)}</h1>${dot}${right}</header>`;
}

function bind(root = $app) {
  root.querySelectorAll('[data-act="back"]').forEach((b) => b.addEventListener('click', back));
}

// ---------------------------------------------------------------- servers
async function renderServers() {
  if (api.conn.server) api.disconnect();
  const list = await store.servers();
  $app.innerHTML = `${topBar('LineGuard', { backBtn: false, right: '<button class="icon" data-go="settings" aria-label="Settings">⚙</button>' })}
  <main class="pad">
    ${list.length ? '<h2>Your LineGuard connections</h2>' : `<div class="hero"><img src="logo-mark.svg" alt="">
      <p>Pair this phone with a LineGuard laptop or server to see its hotspots and drive to them.</p></div>`}
    <ul class="cards">${list.map((s) => `<li><button class="card" data-server="${s.id}">
      <strong>${esc(s.name)}</strong><span>${s.hosted ? 'Online server' : 'Laptop over Wi-Fi'} · ${esc(s.urls[0])}</span>
      ${s.lastSeen ? `<span class="muted">Last connected ${new Date(s.lastSeen).toLocaleString()}</span>` : ''}
    </button></li>`).join('')}</ul>
    <button class="primary wide" data-go="pair">Pair with a LineGuard</button>
    <button class="ghost wide" id="demo">Try the demo</button>
    ${list.length ? '' : '<p class="muted center">The demo has sample hotspots on a simulated 33 kV line, so you can see how the app works before pairing.</p>'}
  </main>`;
  bind();
  $app.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));
  $app.querySelector('#demo').addEventListener('click', async () => {
    await api.connect(api.DEMO);
    go('flights');
  });
  $app.querySelectorAll('[data-server]').forEach((b) => b.addEventListener('click', async () => {
    const s = list.find((x) => x.id === b.dataset.server);
    await api.connect(s);
    go('flights');
  }));
}

// ---------------------------------------------------------------- pairing
function renderPair() {
  const pre = S.pairPrefill;
  const canScan = Capacitor.isNativePlatform();
  $app.innerHTML = `${topBar('Pair with LineGuard')}
  <main class="pad">
    <ol class="steps">
      <li>On the laptop, open the LineGuard dashboard and choose <b>Connect a phone</b>. On a hosted LineGuard, do the same in the browser.</li>
      <li>${canScan ? 'Scan the QR code it shows, or type the address and 6-digit code.' : 'Type the address and 6-digit code it shows.'}</li>
    </ol>
    ${canScan ? '<button class="primary wide" id="scan">Scan QR code</button>' : ''}
    <form id="pair-form" class="form">
      <p class="banner" id="p-check" ${pre ? '' : 'hidden'}></p>
      <label>LineGuard address<input id="p-url" inputmode="url" autocomplete="off" placeholder="10.42.0.1 or lineguard.openworks.co.za" value="${esc(pre ? pre.urls[0] : '')}"></label>
      <label>Pairing code<input id="p-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="6 digits" value="${esc(pre ? pre.code : '')}"></label>
      <label>Name for this phone<input id="p-name" maxlength="60" placeholder="e.g. Bakkie 2, Jan's phone"></label>
      <button class="primary wide" type="submit">Pair</button>
      <p class="error" id="p-err" role="alert"></p>
    </form>
  </main>`;
  bind();
  const err = $app.querySelector('#p-err');
  const check = $app.querySelector('#p-check');
  // A code from a QR or a link is never paired automatically: show where it points and let the user confirm.
  const showCheck = (info) => {
    const hostOf = (u) => { try { return new URL(u).host; } catch { return u; } };
    const urls = api.pairingUrls(info.urls);
    if (!urls.length) {
      check.textContent = 'This code points to an address LineGuard won\'t use (plain http on the internet). Type the address shown on the dashboard instead.';
    } else {
      const more = urls.slice(1).map(hostOf);
      check.textContent = `Check this is your LineGuard before pairing: "${info.name}" at ${hostOf(urls[0])}`
        + (more.length ? ` (on this Wi-Fi it may also answer at ${more.join(', ')}).` : '.');
    }
    check.hidden = false;
  };
  if (pre) showCheck(pre);
  const doPair = async (info) => {
    err.textContent = 'Pairing...';
    try {
      const name = $app.querySelector('#p-name').value.trim() || 'Phone';
      const server = await api.pair(info, name);
      S.pairPrefill = null;
      await api.connect(server);
      S.back = ['servers'];
      S.screen = 'flights';
      render();
    } catch (e) {
      err.textContent = e.message;
    }
  };
  if (canScan) {
    $app.querySelector('#scan').addEventListener('click', async () => {
      const text = await scanQr().catch((e) => { err.textContent = e.message; return null; });
      if (!text) return;
      const info = api.parsePairLink(text);
      if (!info) { err.textContent = 'That QR code is not a LineGuard pairing code.'; return; }
      S.pairPrefill = info;
      $app.querySelector('#p-url').value = info.urls[0];
      $app.querySelector('#p-code').value = info.code;
      showCheck(info);
      err.textContent = 'Check the address, then tap Pair.';
    });
  }
  $app.querySelector('#pair-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const url = api.normaliseUrl($app.querySelector('#p-url').value);
    const code = $app.querySelector('#p-code').value.trim();
    if (!url || !/^\d{6}$/.test(code)) { err.textContent = 'Enter the address and the 6-digit code from the dashboard.'; return; }
    const p = S.pairPrefill;
    // the QR's other addresses are only used if the address shown is still the QR's own first address
    const urls = p && p.code === code && api.normaliseUrl(p.urls[0]) === url ? p.urls : [url];
    doPair({ urls, code, name: p ? p.name : 'LineGuard' });
  });
}

async function scanQr() {
  const { BarcodeScanner, BarcodeFormat } = await import('@capacitor-mlkit/barcode-scanning');
  if (Capacitor.getPlatform() === 'android') {
    const { available } = await BarcodeScanner.isGoogleBarcodeScannerModuleAvailable();
    if (!available) {
      await BarcodeScanner.installGoogleBarcodeScannerModule();
      throw new Error('The QR scanner is being installed. Try again in a moment, or type the code.');
    }
  } else {
    const p = await BarcodeScanner.requestPermissions();
    if (p.camera !== 'granted' && p.camera !== 'limited') throw new Error('Camera permission is needed to scan. You can type the code instead.');
  }
  const { barcodes } = await BarcodeScanner.scan({ formats: [BarcodeFormat.QrCode] });
  return barcodes.length ? barcodes[0].rawValue : null;
}

// ---------------------------------------------------------------- flights
async function renderFlights() {
  const c = api.conn;
  $app.innerHTML = `${topBar(c.server ? c.server.name : 'Flights')}<main class="pad"><p class="muted">Loading flights...</p></main>`;
  bind();
  const { list, live } = await api.flights();
  const pending = await api.pendingCount();
  const done = list.filter((f) => f.status === 'done');
  $app.innerHTML = `${topBar(c.server.name)}
  <main class="pad">
    ${c.unpaired ? '<p class="banner bad">This phone was unpaired from the dashboard. Pair it again to get updates.</p>' : ''}
    ${c.server.demo ? `<p class="banner">Sample data from a simulated 33 kV collector line in the Karoo. Changes you make stay on this phone.
      <button class="link-btn" id="demo-reset">Reset demo</button></p>` : ''}
    ${!live ? `<p class="banner">${list.length ? 'Not connected: showing the flights saved on this phone.' : `Can't reach ${esc(c.server.name)}. Check the phone is on the laptop's Wi-Fi, or has signal for an online LineGuard.`}</p>` : ''}
    ${pending ? `<p class="banner">${pending} change${pending > 1 ? 's' : ''} waiting to send. ${live ? 'Sending...' : 'They send automatically when connected.'}</p>` : ''}
    <h2>Flights</h2>
    <ul class="cards">${done.map((f) => `<li><button class="card" data-flight="${f.id}">
      <strong>${esc(f.name)}</strong>
      <span>${f.open || 0} open of ${f.hotspots}${f.major_open ? ` · <b class="sev-major">${f.major_open} major</b>` : ''}</span>
      <span class="muted">${esc(when(f.flown || f.created))}</span>
    </button></li>`).join('') || '<li class="muted">No processed flights yet.</li>'}</ul>
    ${c.server.demo ? '' : '<button class="ghost wide" id="refresh">Refresh</button>'}
  </main>`;
  bind();
  $app.querySelector('#refresh')?.addEventListener('click', async () => { await api.check(); render(); });
  $app.querySelector('#demo-reset')?.addEventListener('click', async () => { await api.resetDemo(); render(); });
  $app.querySelectorAll('[data-flight]').forEach((b) => b.addEventListener('click', async () => {
    S.flight = list.find((f) => String(f.id) === b.dataset.flight);
    S.selected = null;
    go('flight');
  }));
  cleanup.push(api.onConn(() => {}));
}

// ---------------------------------------------------------------- one flight: map and list
async function loadFlight() {
  const d = await api.flightData(S.flight.id);
  S.hotspots = d.hotspots;
  S.power = d.power;
  return d.live;
}

async function renderFlight() {
  const f = S.flight;
  $app.innerHTML = `${topBar(f.name)}<main class="flight"><p class="pad muted">Loading hotspots...</p></main>`;
  bind();
  const live = await loadFlight();
  const demo = api.conn.server.demo;
  const open = S.hotspots.filter((h) => h.status === 'open');
  const counts = ['major', 'probable', 'possible'].map((s) => [s, open.filter((h) => h.severity === s).length]);
  $app.innerHTML = `${topBar(f.name)}
  <main class="flight">
    <div class="summary">${counts.map(([s, n]) => `<span class="pill ${s}">${n} ${SEV[s].toLowerCase()}</span>`).join('')}
      <span class="muted" id="offline-state">${demo ? 'Sample data' : live ? 'Saving for offline...' : 'Saved copy'}</span></div>
    <div class="tabs" role="tablist">
      <button role="tab" data-tab="map" aria-selected="${S.tab === 'map'}">Map</button>
      <button role="tab" data-tab="list" aria-selected="${S.tab === 'list'}">List</button>
    </div>
    <div id="map" class="map" ${S.tab !== 'map' ? 'hidden' : ''}></div>
    <ul id="list" class="hlist" ${S.tab !== 'list' ? 'hidden' : ''}></ul>
    <div class="drive-bar"><button class="primary big" id="drive" ${open.length ? '' : 'disabled'}>Drive to ${open.length} open hotspot${open.length === 1 ? '' : 's'}</button></div>
  </main>`;
  bind();
  dev.startLocation();
  map = createMap($app.querySelector('#map'), { onSelect: (h) => { S.selected = h.id; go('hotspot'); } });
  map.setPower(S.power);
  map.setHotspots(S.hotspots, S.selected, true);
  cleanup.push(dev.onPosition((h) => map && map.setMe(h.pos, false)));
  if (dev.here.pos) map.setMe(dev.here.pos, false);
  renderList();
  $app.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => {
    S.tab = b.dataset.tab;
    $app.querySelectorAll('[data-tab]').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    $app.querySelector('#map').hidden = S.tab !== 'map';
    $app.querySelector('#list').hidden = S.tab !== 'list';
    if (S.tab === 'map') map.map.invalidateSize();
    else renderList();
  }));
  $app.querySelector('#drive').addEventListener('click', async () => {
    await dev.askCompassPermission();
    go('drive');
  });
  if (live) {
    api.downloadImages(S.hotspots, (i, n) => {
      const el = document.getElementById('offline-state');
      if (el) el.textContent = i === n ? 'Saved for offline' : `Saving photos ${i} of ${n}`;
    });
  }
}

function renderList() {
  const ul = $app.querySelector('#list');
  if (!ul) return;
  const p = dev.here.pos;
  const rows = S.hotspots.slice().sort((a, b) => (a.status === 'open') - (b.status === 'open') || 0)
    .sort((a, b) => (b.status === 'open') - (a.status === 'open') || (p ? distance(p, a) - distance(p, b) : b.dt - a.dt));
  ul.innerHTML = rows.map((h) => `<li><button class="hrow ${h.status}" data-h="${h.id}">
    <span class="dot" style="background:${h.status === 'open' ? SEV_COLOUR[h.severity] : '#9aa3b5'}"></span>
    <span class="hmain"><strong>LG-${h.id} · +${h.dt.toFixed(1)} °C</strong>
      <span class="muted">${esc(towerLabel(h) || `${h.lat.toFixed(5)}, ${h.lon.toFixed(5)}`)}</span></span>
    <span class="hside">${p ? fmtDistance(distance(p, h)) : ''}<br><span class="muted">${STATUS[h.status]}${h.pending ? ' ·' : ''}</span></span>
  </button></li>`).join('');
  ul.querySelectorAll('[data-h]').forEach((b) => b.addEventListener('click', () => { S.selected = +b.dataset.h; go('hotspot'); }));
}

function when(s) {
  if (!s) return '';
  const m = /^(\d{4})[-:](\d\d)[-:](\d\d)[ T](\d\d:\d\d)/.exec(s);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}` : s;
}

function towerLabel(h) {
  const parts = [];
  if (h.tower_ref) parts.push(`${h.tower_kind === 'pole' ? 'Pole' : 'Tower'} ${h.tower_ref}`);
  if (h.line_name || h.line_voltage_kv) parts.push([h.line_name, h.line_voltage_kv ? `${h.line_voltage_kv} kV` : ''].filter(Boolean).join(' '));
  return parts.join(', ');
}

// ---------------------------------------------------------------- one hotspot
async function renderHotspot() {
  const h = S.hotspots.find((x) => x.id === S.selected);
  if (!h) return back();
  const p = dev.here.pos;
  const coords = `${h.lat.toFixed(7)}, ${h.lon.toFixed(7)}`;
  $app.innerHTML = `${topBar(`Hotspot LG-${h.id}`)}
  <main class="pad hotspot">
    <div class="rise"><span class="big-num">+${h.dt.toFixed(1)} °C</span><span class="pill ${h.severity}">${SEV[h.severity]}</span></div>
    <p class="muted">Hotter than the same point on the other phases. Seen in ${h.photos} of ${h.seen} photos.</p>
    ${towerLabel(h) ? `<p class="tower">${esc(towerLabel(h))}${h.tower_dist_m != null ? `, ${Math.round(h.tower_dist_m)} m` : ''}</p>` : ''}
    ${h.prev_dt != null ? `<p class="banner">Seen on an earlier flight at +${h.prev_dt.toFixed(1)} °C.</p>` : ''}
    <div class="photos"><figure><img id="i-t" alt="Thermal close-up"><figcaption>Thermal</figcaption></figure>
      ${h.colour_crop ? '<figure><img id="i-c" alt="Colour close-up"><figcaption>Colour</figcaption></figure>' : ''}</div>
    <p class="coords"><code>${coords}</code>${p ? ` · ${fmtDistance(distance(p, h))} ${compassShort(bearing(p, h))}` : ''}</p>
    <div class="row"><button class="primary" id="nav">Directions</button><button class="ghost" id="copy">Copy coordinates</button></div>
    <h2>On site</h2>
    <div class="status-row">${Object.entries(STATUS).map(([k, v]) => `<button class="st ${h.status === k ? 'on' : ''}" data-st="${k}">${v}</button>`).join('')}</div>
    <label class="note">Note<textarea id="note" rows="3" placeholder="What was found">${esc(h.note || '')}</textarea></label>
    ${h.pending ? '<p class="muted">Changes saved on this phone; they send when connected.</p>' : ''}
  </main>`;
  bind();
  api.image(h.thermal_crop).then((u) => { const i = $app.querySelector('#i-t'); if (i && u) i.src = u; });
  if (h.colour_crop) api.image(h.colour_crop).then((u) => { const i = $app.querySelector('#i-c'); if (i && u) i.src = u; });
  $app.querySelector('#nav').addEventListener('click', () => dev.openUrl(dev.directionsUrl(h.lat, h.lon, `LG-${h.id}`, S.settings.mapsApp)));
  $app.querySelector('#copy').addEventListener('click', async (e) => {
    try { await navigator.clipboard.writeText(coords); e.target.textContent = 'Copied'; } catch { e.target.textContent = coords; }
  });
  $app.querySelectorAll('[data-st]').forEach((b) => b.addEventListener('click', async () => {
    await api.change(S.flight.id, h, { status: b.dataset.st });
    render();
  }));
  $app.querySelector('#note').addEventListener('change', (e) => api.change(S.flight.id, h, { note: e.target.value }));
}

// ---------------------------------------------------------------- drive mode
const D = { route: [], idx: 0, announced: new Set(), arrived: false, lastSpoken: 0 };

function stopDrive() {
  dev.keepAwake(false);
}

function nextTarget() {
  return D.route[D.idx] || null;
}

function startRoute() {
  const open = S.hotspots.filter((h) => h.status === 'open');
  D.route = plan(dev.here.pos, open, { majorFirst: S.settings.majorFirst });
  D.idx = 0;
  D.announced = new Set();
  D.arrived = false;
}

function announceNext() {
  const t = nextTarget();
  const p = dev.here.pos;
  if (!t) { if (S.settings.voice) dev.speak('All hotspots on this flight are done.'); return; }
  if (!S.settings.voice) return;
  const left = D.route.length - D.idx;
  const where = p ? `, ${spokenDistance(distance(p, t))} ${compassWord(bearing(p, t))}` : '';
  dev.speak(`Next: hotspot ${t.id}, ${SEV[t.severity].toLowerCase()}${where}. ${left} to go.`);
}

function renderDrive() {
  startRoute();
  dev.startLocation();
  dev.keepAwake(true);
  $app.innerHTML = `<main class="drive">
    <header class="dbar"><button class="icon light" data-act="back" aria-label="Stop driving">‹</button>
      <div><div id="d-progress" class="muted-l"></div><div id="d-title" class="d-title"></div></div>
      <button class="icon light" id="d-voice" aria-label="Voice">${S.settings.voice ? '🔊' : '🔇'}</button></header>
    <section class="dial">
      <div class="arrow-wrap"><svg id="d-arrow" viewBox="0 0 100 100" aria-hidden="true"><path d="M50 6 L80 86 L50 70 L20 86 Z"/></svg>
        <span id="d-north" class="north" hidden>N</span></div>
      <div class="dist"><span id="d-dist">--</span><span id="d-dir" class="muted-l"></span></div>
    </section>
    <section id="d-card" class="dcard"></section>
    <nav class="dactions">
      <button id="d-fixed" class="ok">Repaired</button>
      <button id="d-notfault">Not a fault</button>
      <button id="d-skip">Skip</button>
      <button id="d-maps">Road directions</button>
    </nav>
    <p id="d-gps" class="gps muted-l"></p>
  </main>`;
  bind();
  const el = (id) => $app.querySelector(id);
  const updateCard = async () => {
    const t = nextTarget();
    el('#d-progress').textContent = t ? `Hotspot ${D.idx + 1} of ${D.route.length}` : 'Finished';
    el('#d-title').textContent = t ? `LG-${t.id} · ${SEV[t.severity]} +${t.dt.toFixed(1)} °C` : 'All done on this flight';
    el('#d-card').innerHTML = t ? `<img id="d-img" alt="Thermal close-up"><div><b>${esc(towerLabel(t) || 'No tower recorded')}</b>
      <span class="muted-l">${t.lat.toFixed(6)}, ${t.lon.toFixed(6)}</span></div>` : '<div><b>Every open hotspot has been visited.</b></div>';
    $app.querySelectorAll('.dactions button').forEach((b) => (b.disabled = !t));
    if (t) api.image(t.thermal_crop).then((u) => { const i = el('#d-img'); if (i && u) i.src = u; });
  };
  const advance = (speak = true) => {
    D.idx++;
    D.announced = new Set();
    D.arrived = false;
    updateCard();
    update();
    if (speak) announceNext();
  };
  const mark = async (status) => {
    const t = nextTarget();
    if (!t) return;
    await api.change(S.flight.id, t, { status });
    advance();
  };
  el('#d-fixed').addEventListener('click', () => mark('repaired'));
  el('#d-notfault').addEventListener('click', () => mark('dismissed'));
  el('#d-skip').addEventListener('click', () => {
    const t = D.route.splice(D.idx, 1)[0];
    D.route.push(t);
    D.idx--;
    advance();
  });
  el('#d-maps').addEventListener('click', () => {
    const t = nextTarget();
    if (t) dev.openUrl(dev.directionsUrl(t.lat, t.lon, `LG-${t.id}`, S.settings.mapsApp));
  });
  el('#d-voice').addEventListener('click', (e) => {
    S.settings.voice = !S.settings.voice;
    saveSettings();
    e.target.textContent = S.settings.voice ? '🔊' : '🔇';
  });

  function update() {
    const t = nextTarget();
    const p = dev.here.pos;
    el('#d-gps').textContent = p ? `GPS ±${Math.round(p.acc || 0)} m` : (dev.here.error || 'Waiting for GPS...');
    if (!t || !p) { el('#d-dist').textContent = '--'; el('#d-dir').textContent = ''; return; }
    const d = distance(p, t);
    const b = bearing(p, t);
    const hd = dev.heading();
    el('#d-arrow').style.transform = `rotate(${hd == null ? b : b - hd}deg)`;
    el('#d-north').hidden = hd != null;
    el('#d-dist').textContent = fmtDistance(d);
    el('#d-dir').textContent = hd == null ? `${compassShort(b)} · north is up` : compassShort(b);
    $app.querySelector('.drive').classList.toggle('arrived', d <= S.settings.arrival);
    if (!S.settings.voice) return;
    if (d <= S.settings.arrival && !D.arrived) {
      D.arrived = true;
      dev.speak(`Arrived at hotspot ${t.id}. ${towerLabel(t) ? towerLabel(t) + '. ' : ''}${SEV[t.severity]}, ${Math.round(t.dt)} degrees above the other phases.`);
      return;
    }
    for (const mark of [2000, 1000, 500, 200, 100]) {
      if (d <= mark && d > S.settings.arrival && !D.announced.has(mark)) {
        [2000, 1000, 500, 200, 100].filter((m) => m >= mark).forEach((m) => D.announced.add(m));
        if (Date.now() - D.lastSpoken > 8000) {
          D.lastSpoken = Date.now();
          dev.speak(`Hotspot ${t.id} in ${spokenDistance(d)}, ${compassWord(b)}.`);
        }
        break;
      }
    }
  }
  updateCard();
  update();
  setTimeout(announceNext, 400);
  cleanup.push(dev.onPosition(update));
}

// ---------------------------------------------------------------- settings
async function renderSettings() {
  const list = await store.servers();
  const ios = Capacitor.getPlatform() === 'ios';
  $app.innerHTML = `${topBar('Settings')}
  <main class="pad">
    <h2>Driving</h2>
    <label class="switch"><input type="checkbox" id="s-voice" ${S.settings.voice ? 'checked' : ''}> Spoken directions</label>
    <label class="switch"><input type="checkbox" id="s-major" ${S.settings.majorFirst ? 'checked' : ''}> Visit major hotspots first</label>
    <label>Arrival distance
      <select id="s-arrival">${[20, 35, 50, 80].map((m) => `<option value="${m}" ${S.settings.arrival === m ? 'selected' : ''}>${m} m</option>`).join('')}</select></label>
    <label>Road directions open in
      <select id="s-maps">${[['google', 'Google Maps'], ...(ios ? [['apple', 'Apple Maps']] : []), ['waze', 'Waze'], ['other', ios ? 'Apple Maps (geo link)' : 'Any maps app (OsmAnd, Organic Maps...)']]
        .map(([k, v]) => `<option value="${k}" ${S.settings.mapsApp === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
    <p class="muted">For directions without signal, download the area in Google Maps (Offline maps) or use OsmAnd or Organic Maps with the region downloaded. LineGuard's own arrow and distance work from GPS alone.</p>
    <h2>Connections</h2>
    <ul class="cards">${list.map((s) => `<li class="card flat"><strong>${esc(s.name)}</strong><span>${esc(s.urls[0])}</span>
      <button class="ghost small" data-forget="${s.id}">Forget</button></li>`).join('') || '<li class="muted">None yet.</li>'}</ul>
    <p class="muted">Forgetting a connection removes its pairing and everything saved from it on this phone.</p>
    <h2>About</h2>
    <p class="muted">LineGuard app ${__APP_VERSION__} by OpenWorks IT, free software under the GNU AGPL v3. Your location is used on this phone only, to guide you to each hotspot, and is never sent anywhere. Map data © OpenStreetMap contributors.</p>
    <div class="row"><button class="ghost" id="privacy">Privacy policy</button><button class="ghost" id="source">Source code</button></div>
    <button class="ghost wide" id="licences">Open-source licences</button>
    <pre class="licences" id="licence-text" hidden></pre>
  </main>`;
  bind();
  $app.querySelector('#privacy').addEventListener('click', () => dev.openUrl(PRIVACY_URL));
  $app.querySelector('#source').addEventListener('click', () => dev.openUrl(SOURCE_URL));
  $app.querySelector('#licences').addEventListener('click', async (e) => {
    const pre = $app.querySelector('#licence-text');
    try {
      const r = await fetch('licenses.txt');
      pre.textContent = r.ok ? await r.text() : 'The licence list is included in release builds.';
    } catch { pre.textContent = 'The licence list is included in release builds.'; }
    pre.hidden = false;
    e.target.hidden = true;
  });
  const on = (id, fn) => $app.querySelector(id).addEventListener('change', (e) => { fn(e.target); saveSettings(); });
  on('#s-voice', (t) => (S.settings.voice = t.checked));
  on('#s-major', (t) => (S.settings.majorFirst = t.checked));
  on('#s-arrival', (t) => (S.settings.arrival = +t.value));
  on('#s-maps', (t) => (S.settings.mapsApp = t.value));
  $app.querySelectorAll('[data-forget]').forEach((b) => b.addEventListener('click', async () => {
    await store.removeServer(b.dataset.forget);
    render();
  }));
}

// ---------------------------------------------------------------- start
async function handleLink(url) {
  const info = api.parsePairLink(url);
  if (!info) return;
  S.pairPrefill = info;
  if (S.screen !== 'pair') go('pair');
  else render();
}

async function start() {
  await loadSettings();
  if (Capacitor.isNativePlatform()) {
    App.addListener('appUrlOpen', ({ url }) => handleLink(url));
    App.addListener('backButton', () => { if (!back()) App.exitApp(); });
    App.addListener('resume', () => api.check());
    const launch = await App.getLaunchUrl();
    if (launch && launch.url) { await handleLink(launch.url); return; }
  }
  const params = new URLSearchParams(location.search);
  if (params.get('pair')) { await handleLink(params.get('pair')); return; }
  const list = await store.servers();
  if (list.length === 1) {
    await api.connect(list[0]);
    S.back = ['servers'];
    S.screen = 'flights';
  }
  render();
}

api.onConn(() => {
  const el = document.querySelector('.bar .link');
  const c = api.conn;
  if (el && c.server && !c.server.demo) {
    el.className = `link ${c.online ? 'on' : 'off'}`;
    el.textContent = c.online ? 'Connected' : 'Offline';
  }
});

start();
