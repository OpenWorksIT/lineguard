// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// Everything the app needs offline lives in IndexedDB on the phone:
// servers, flights, hotspots, close-up photos, map tiles and changes waiting to be sent.
import { createStore, get, set, del, keys, entries } from 'idb-keyval';

const data = createStore('lineguard', 'data');
const images = createStore('lineguard-images', 'images');
const tiles = createStore('lineguard-tiles', 'tiles');

export const db = {
  get: (k) => get(k, data),
  set: (k, v) => set(k, v, data),
  del: (k) => del(k, data),
  keys: () => keys(data),
};

export const imageCache = {
  get: (k) => get(k, images),
  set: (k, v) => set(k, v, images),
  keys: () => keys(images),
};

const MAX_TILES = 6000;
let tileCount = null;
export const tileCache = {
  get: (k) => get(k, tiles),
  async set(k, v) {
    if (tileCount === null) tileCount = (await keys(tiles)).length;
    if (tileCount >= MAX_TILES) {
      // drop the oldest quarter
      const all = (await entries(tiles)).sort((a, b) => a[1].t - b[1].t);
      await Promise.all(all.slice(0, Math.floor(MAX_TILES / 4)).map(([key]) => del(key, tiles)));
      tileCount = all.length - Math.floor(MAX_TILES / 4);
    }
    tileCount++;
    return set(k, { blob: v, t: Date.now() }, tiles);
  },
};

// ---- servers
export async function servers() {
  return (await db.get('servers')) || [];
}
export async function saveServer(s) {
  const list = await servers();
  const i = list.findIndex((x) => x.id === s.id);
  if (i >= 0) list[i] = s; else list.push(s);
  await db.set('servers', list);
}
// Forgetting a connection also deletes everything saved from it: its token, flights,
// hotspots, photos, its own map tiles and any changes not yet sent.
export async function removeServer(id) {
  await db.set('servers', (await servers()).filter((s) => s.id !== id));
  const mine = (k) => typeof k === 'string' && (k === `flights:${id}` || k.startsWith(`hotspots:${id}:`) || k.startsWith(`power:${id}:`) || k.startsWith(`${id}:`));
  await Promise.all((await db.keys()).filter(mine).map((k) => db.del(k)));
  await Promise.all((await keys(images)).filter(mine).map((k) => del(k, images)));
  await Promise.all((await keys(tiles)).filter(mine).map((k) => del(k, tiles)));
  await db.set('outbox', (await outbox()).filter((c) => c.server !== id));
}

// ---- changes made while out of range
export async function outbox() {
  return (await db.get('outbox')) || [];
}
export async function queueChange(change) {
  const list = await outbox();
  const same = list.findIndex((c) => c.server === change.server && c.hid === change.hid);
  if (same >= 0) list[same] = { ...list[same], ...change };
  else list.push(change);
  await db.set('outbox', list);
}
export async function setOutbox(list) {
  await db.set('outbox', list);
}
