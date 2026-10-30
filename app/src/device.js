// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// Phone features: GPS, compass, voice, keeping the screen on, opening a maps app.
import { Capacitor } from '@capacitor/core';
import { Geolocation } from '@capacitor/geolocation';
import { TextToSpeech } from '@capacitor-community/text-to-speech';
import { KeepAwake } from '@capacitor-community/keep-awake';
import { AppLauncher } from '@capacitor/app-launcher';

// ---- position
export const here = { pos: null, compass: null, error: null };
const subs = new Set();
export const onPosition = (fn) => (subs.add(fn), () => subs.delete(fn));
const emit = () => subs.forEach((fn) => fn(here));
let watchId = null;

export async function startLocation() {
  if (watchId !== null) return;
  try {
    if (Capacitor.isNativePlatform()) {
      const perm = await Geolocation.requestPermissions({ permissions: ['location'] });
      if (perm.location === 'denied') throw new Error('Location permission was refused. Allow it in the phone settings.');
    }
    watchId = await Geolocation.watchPosition({ enableHighAccuracy: true, timeout: 20000, maximumAge: 1000 }, (p, err) => {
      if (err || !p) {
        here.error = (err && err.message) || 'No GPS fix yet.';
      } else {
        const c = p.coords;
        here.pos = { lat: c.latitude, lon: c.longitude, acc: c.accuracy, speed: c.speed, heading: c.heading, t: p.timestamp };
        here.error = null;
      }
      emit();
    });
  } catch (e) {
    here.error = e.message || String(e);
    emit();
  }
  startCompass();
}

let compassOn = false;
function startCompass() {
  if (compassOn || typeof window === 'undefined') return;
  compassOn = true;
  const handler = (e) => {
    let h = null;
    if (typeof e.webkitCompassHeading === 'number') h = e.webkitCompassHeading;           // iOS
    else if (e.absolute && typeof e.alpha === 'number') h = (360 - e.alpha) % 360;        // Android
    if (h !== null) {
      const screen = (window.screen.orientation && window.screen.orientation.angle) || 0;
      here.compass = (h + screen + 360) % 360;
      emit();
    }
  };
  window.addEventListener('deviceorientationabsolute', handler, true);
  window.addEventListener('deviceorientation', handler, true);
}

// iOS asks for compass permission only after a tap.
export async function askCompassPermission() {
  const D = window.DeviceOrientationEvent;
  if (D && typeof D.requestPermission === 'function') {
    try { await D.requestPermission(); } catch { /* user said no */ }
  }
}

// Which way the phone (or vehicle) points: GPS course when moving, compass when still.
export function heading() {
  const p = here.pos;
  if (p && p.speed != null && p.speed > 1.5 && p.heading != null && !Number.isNaN(p.heading)) return p.heading;
  return here.compass;
}

// ---- voice
export async function speak(text) {
  try {
    if (Capacitor.isNativePlatform()) {
      await TextToSpeech.stop().catch(() => {});
      await TextToSpeech.speak({ text, lang: 'en-ZA', rate: 1.0, pitch: 1.0, volume: 1.0, category: 'playback' });
    } else if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'en-ZA';
      window.speechSynthesis.speak(u);
    }
  } catch { /* voice is a nice-to-have */ }
}

// ---- screen
export async function keepAwake(on) {
  if (!Capacitor.isNativePlatform()) return;
  try { on ? await KeepAwake.keepAwake() : await KeepAwake.allowSleep(); } catch { /* ignore */ }
}

// ---- hand-off for road directions
export function directionsUrl(lat, lon, label, app = 'google') {
  const ll = `${lat.toFixed(7)},${lon.toFixed(7)}`;
  if (app === 'apple') return `maps://?daddr=${ll}&dirflg=d`;
  if (app === 'waze') return `https://waze.com/ul?ll=${ll}&navigate=yes`;
  if (app === 'other') return Capacitor.getPlatform() === 'android' ? `geo:${ll}?q=${ll}(${encodeURIComponent(label)})` : `maps://?daddr=${ll}`;
  return `https://www.google.com/maps/dir/?api=1&destination=${ll}&travelmode=driving`;
}

export async function openUrl(url) {
  if (Capacitor.isNativePlatform()) {
    try { await AppLauncher.openUrl({ url }); return; } catch { /* fall back */ }
  }
  window.open(url, '_blank');
}
