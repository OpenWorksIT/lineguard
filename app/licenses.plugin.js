// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// Writes dist/licenses.txt: the licence of every open-source package bundled into the app,
// plus the native libraries the Android and iOS builds link. Shown in Settings > Open-source licences.
import fs from 'node:fs';
import path from 'node:path';

const NATIVE = `
Native libraries in the phone builds
====================================
Android: AndroidX (AppCompat, Core, Activity, Fragment, WebKit, CoordinatorLayout, SplashScreen), CameraX,
Kotlin standard library and kotlinx.coroutines, Gson - Apache License 2.0. Ionic iongeolocation-android - MIT.
Android: Google Play services (code scanner, location) and Google ML Kit barcode scanning - proprietary,
under the Google APIs Terms of Service; used under the additional permission in LineGuard's NOTICE.
iOS: Capacitor and CapacitorCordova - MIT. Ionic IONGeolocationLib - MIT.
iOS: Google ML Kit (GoogleMLKit/BarcodeScanning) and its Google dependencies - proprietary, under the
Google APIs Terms of Service; used under the additional permission in LineGuard's NOTICE.
Map data (c) OpenStreetMap contributors, Open Database Licence (ODbL).
`;

function readPkg(dir) {
  try { return JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8')); } catch { return null; }
}

function licenceText(dir) {
  const f = fs.readdirSync(dir).find((n) => /^(licen[cs]e|copying)(\.(md|txt))?$/i.test(n));
  return f ? fs.readFileSync(path.join(dir, f), 'utf8').trim() : '';
}

export default function licenses() {
  return {
    name: 'lineguard-licences',
    apply: 'build',
    generateBundle() {
      const root = process.cwd();
      const seen = new Map();
      const walk = (name) => {
        if (seen.has(name)) return;
        const dir = path.join(root, 'node_modules', name);
        const pkg = readPkg(dir);
        if (!pkg) return;
        seen.set(name, { version: pkg.version, license: pkg.license || '(see text)', text: licenceText(dir) });
        Object.keys(pkg.dependencies || {}).forEach(walk);
      };
      Object.keys(readPkg(root).dependencies || {}).forEach(walk);
      const parts = ['LineGuard app - open-source licences', '=====================================',
        'LineGuard itself: GNU Affero General Public License v3.0 or later, (C) 2026 OpenWorks IT (Pty) Ltd.',
        'Source: https://github.com/OpenWorksIT/lineguard', ''];
      for (const [name, p] of [...seen.entries()].sort()) {
        parts.push('-'.repeat(72), `${name} ${p.version} - ${p.license}`, '', p.text || '(licence text not included in the package)', '');
      }
      parts.push('-'.repeat(72), NATIVE.trim(), '');
      this.emitFile({ type: 'asset', fileName: 'licenses.txt', source: parts.join('\n') });
    },
  };
}
