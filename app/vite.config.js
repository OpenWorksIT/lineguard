// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
import { defineConfig } from 'vite';
import pkg from './package.json' with { type: 'json' };
import licenses from './licenses.plugin.js';

// Content Security Policy for the built app. Requests to LineGuard servers and map tiles go through
// native HTTP on the phone (not subject to this policy), so the web view itself needs no network access.
// This blocks injected markup and inline script, but it is a second line of defence only: script that
// did run could still call native plugins. The first line is that all server data is escaped or
// reduced to plain values before display (see clean* in src/api.js).
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

const csp = {
  name: 'lineguard-csp',
  apply: 'build',
  transformIndexHtml: () => [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' }],
};

export default defineConfig({
  base: './',
  plugins: [csp, licenses()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: { outDir: 'dist', target: 'es2020', assetsInlineLimit: 0 },
  server: { host: '127.0.0.1', port: 5173 },
});
