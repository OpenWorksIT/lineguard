// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// One HTTP helper for the browser and the phone.
// On the phone, requests go through native HTTP, which avoids CORS and lets the app
// reach a laptop on plain http:// over the vehicle's Wi-Fi.
import { Capacitor, CapacitorHttp } from '@capacitor/core';

export class HttpError extends Error {
  constructor(status, message, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function b64ToBlob(b64, type) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: type || 'application/octet-stream' });
}

export async function http(method, url, { token, body, blob = false, timeout = 8000 } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let status;
  let data;
  if (Capacitor.isNativePlatform()) {
    const r = await CapacitorHttp.request({
      method, url, headers, data: body,
      responseType: blob ? 'blob' : 'json',
      connectTimeout: timeout, readTimeout: timeout * 3,
    });
    status = r.status;
    const type = r.headers['Content-Type'] || r.headers['content-type'];
    data = blob && status < 300 ? b64ToBlob(r.data, type) : r.data;
    if (!blob && typeof data === 'string') {
      try { data = JSON.parse(data); } catch { /* plain text */ }
    }
  } else {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout * (blob ? 3 : 1));
    try {
      const r = await fetch(url, {
        method, headers, body: body !== undefined ? JSON.stringify(body) : undefined, signal: ctrl.signal,
      });
      status = r.status;
      if (blob && r.ok) data = await r.blob();
      else {
        const text = await r.text();
        try { data = JSON.parse(text); } catch { data = text; }
      }
    } finally {
      clearTimeout(timer);
    }
  }
  if (status >= 300) {
    // redirects aren't followed: a LineGuard address that redirects (e.g. http to https) is the wrong address
    const msg = (data && typeof data.error === 'string' && data.error) || (status < 400
      ? `That address redirects elsewhere (HTTP ${status}). Use the https:// address.`
      : `HTTP ${status}`);
    throw new HttpError(status, msg, data);
  }
  return data;
}
