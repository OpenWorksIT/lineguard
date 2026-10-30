// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 OpenWorks IT (Pty) Ltd
// LineGuard dashboard. Plain JavaScript, no build step, works offline.
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const SEV = { major: "#c8281e", probable: "#e8731a", possible: "#d9a50d" };
  const SEV_NAME = { major: "Major", probable: "Probable", possible: "Possible" };
  const STATUS_NAME = { open: "Open", repaired: "Repaired", dismissed: "Not a fault" };
  const state = { flights: [], flightId: null, hotspots: [], power: null, selected: null, filter: "open", sev: null, status: null };

  const api = async (path, opts = {}) => {
    // X-LineGuard marks the request as coming from this dashboard (the server refuses changes without it)
    const headers = opts.body instanceof FormData ? { "X-LineGuard": "1" } : { "Content-Type": "application/json", "X-LineGuard": "1" };
    const r = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `${r.status} ${r.statusText}`);
    return body;
  };

  const whereText = (h) => {
    const parts = [];
    if (h.tower_ref) parts.push(`${h.tower_kind === "pole" ? "Pole" : "Tower"} ${h.tower_ref}`);
    const line = [h.line_name, h.line_voltage_kv ? `${h.line_voltage_kv} kV` : ""].filter(Boolean).join(" ");
    if (line) parts.push(`${line} line`);
    return parts.join(", ");
  };

  // ---- map
  const map = L.map("map").setView([-30.5, 24], 5);
  const powerLayer = L.layerGroup().addTo(map);
  const markers = L.layerGroup().addTo(map);
  let track = null;
  let tileErrors = 0;
  function setTiles(url, offline) {
    const layer = L.tileLayer(url, { maxZoom: 21, maxNativeZoom: 19, attribution: offline ? "Offline map tiles" : "© OpenStreetMap contributors" });
    layer.on("tileerror", () => { if (++tileErrors === 3) $("tile-note").hidden = false; });
    layer.on("tileload", () => { tileErrors = 0; $("tile-note").hidden = true; });
    layer.addTo(map);
  }
  const voltageColour = (kv) => kv == null ? "#7a8599" : kv >= 400 ? "#d43ba6" : kv >= 220 ? "#c73030" : kv >= 110 ? "#2b6fd6" : kv >= 50 ? "#2a9d8f" : kv >= 25 ? "#7cae1e" : "#8d6e63";

  function drawPower() {
    powerLayer.clearLayers();
    const p = state.power;
    if (!p) return;
    (p.lines || []).forEach((l) => L.polyline(l.coords, { color: voltageColour(l.voltage_kv), weight: 3, opacity: 0.6 })
      .bindTooltip(`${esc(l.name || "Power line")}${Number(l.voltage_kv) ? `, ${esc(Number(l.voltage_kv))} kV` : ""}`, { sticky: true }).addTo(powerLayer));
    (p.supports || []).forEach((s) => L.circleMarker([s.lat, s.lon], { radius: 3, color: s.source === "client" ? "#1d3f8c" : "#3b4252", weight: 1, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip(`${s.kind === "pole" ? "Pole" : "Tower"} ${esc(s.ref || "")}${s.source === "client" ? " (your list)" : ""}`).addTo(powerLayer));
  }

  function markerStyle(h) {
    const sel = state.selected === h.id;
    if (h.status === "repaired") return { radius: sel ? 10 : 7, color: "#2b8a57", weight: 3, fillColor: "#fff", fillOpacity: 1 };
    if (h.status === "dismissed") return { radius: sel ? 9 : 6, color: "#8a93a6", weight: 2, fillColor: "#fff", fillOpacity: 1 };
    const r = h.severity === "major" ? 10 : h.severity === "probable" ? 8 : 6;
    return { radius: sel ? r + 4 : r, color: sel ? "#15203a" : "#fff", weight: sel ? 4 : 2, fillColor: SEV[h.severity], fillOpacity: 0.95 };
  }

  function drawMap(fit) {
    markers.clearLayers();
    if (track) { track.remove(); track = null; }
    const f = currentFlight();
    const pts = [];
    if (f && f.track && f.track.length) {
      track = L.polyline(f.track, { color: "#1d3f8c", weight: 2, dashArray: "6 6", opacity: 0.6 }).addTo(map);
      pts.push(...f.track);
    }
    visible().forEach((h) => {
      const m = L.circleMarker([h.lat, h.lon], markerStyle(h)).addTo(markers);
      m.bindTooltip(`LG-${h.id}: +${h.dt.toFixed(1)} °C${whereText(h) ? ` · ${esc(whereText(h))}` : ""}`);
      m.on("click", () => select(h.id));
      pts.push([h.lat, h.lon]);
    });
    if (fit && pts.length) map.fitBounds(pts, { padding: [30, 30], maxZoom: 18 });
  }

  // ---- flights
  const currentFlight = () => state.flights.find((f) => f.id === state.flightId);
  const fmtDate = (s) => (!s ? "" : /^\d{4}[-:]\d\d[-:]\d\d/.test(s) ? s.replace("T", " ").replace(/^(\d{4}):(\d\d):/, "$1-$2-").slice(0, 16) : s);

  function renderFlights() {
    const list = $("flight-list");
    list.innerHTML = "";
    $("flights-empty").hidden = state.flights.length > 0;
    state.flights.forEach((f) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = `flight ${f.status}`;
      b.setAttribute("aria-current", String(f.id === state.flightId));
      let meta;
      if (f.status === "done") meta = `${fmtDate(f.flown) || fmtDate(f.created)} · ${f.photos} photos`;
      else if (f.status === "failed") meta = `Could not process: ${f.message}`;
      else if (f.status === "processing") meta = `${f.message} (${Math.round(f.progress * 100)}%)`;
      else meta = "Waiting to be processed";
      const dots = f.status === "done"
        ? `<span class="f-dots">${f.open ? `${f.major_open ? `<span class="major">${f.major_open} major</span>` : ""}<span>${f.open} open</span>` : "<span>No open hotspots</span>"}</span>` : "";
      const bar = f.status === "processing" ? `<span class="progress"><span style="width:${Math.round(f.progress * 100)}%"></span></span>` : "";
      b.innerHTML = `<span class="f-name">${esc(f.name)}</span><span class="f-meta">${esc(meta)}</span>${dots}${bar}`;
      b.addEventListener("click", () => openFlight(f.id));
      li.appendChild(b);
      list.appendChild(li);
    });
  }

  async function loadFlights() {
    const before = currentFlight();
    try { state.flights = await api("/api/flights"); } catch { /* server restarting */ }
    renderFlights();
    const now = currentFlight();
    if (now && before && before.status !== "done" && now.status === "done") openFlight(now.id);
    if (!state.flightId) {
      const first = state.flights.find((f) => f.status === "done");
      if (first) openFlight(first.id);
    }
    const busy = state.flights.some((f) => f.status === "queued" || f.status === "processing");
    setTimeout(loadFlights, busy ? 2000 : 6000);
  }

  async function openFlight(id, keepSelection = false) {
    state.flightId = id;
    if (!keepSelection) { state.selected = null; $("detail").hidden = true; }
    renderFlights();
    const f = currentFlight();
    $("choose-flight").hidden = true;
    $("flight-head").hidden = false;
    $("flight-name").textContent = f.name;
    $("flight-meta").textContent = f.status === "done"
      ? `${fmtDate(f.flown) || fmtDate(f.created)}. ${f.message}.`
      : f.message || "Waiting to be processed";
    $("report-link").href = `/report/${id}`;
    $("kml-link").href = `/export/${id}.kml`;
    $("gpx-link").href = `/export/${id}.gpx`;
    $("csv-link").href = `/export/${id}.csv`;
    const done = f.status === "done";
    state.hotspots = done ? await api(`/api/flights/${id}/hotspots`) : [];
    state.power = done ? await api(`/api/flights/${id}/power`).catch(() => null) : null;
    $("summary").hidden = !done;
    $("map-wrap").hidden = !done;
    renderSummary();
    renderHotspots();
    drawPower();
    drawMap(!keepSelection);
    map.invalidateSize();
  }

  function renderSummary() {
    const open = state.hotspots.filter((h) => h.status === "open");
    ["major", "probable", "possible"].forEach((s) => ($(`n-${s}`).textContent = open.filter((h) => h.severity === s).length));
    $("n-repaired").textContent = state.hotspots.filter((h) => h.status === "repaired").length;
    document.querySelectorAll(".tile[data-sev]").forEach((t) => t.setAttribute("aria-pressed", String(t.dataset.sev === state.sev)));
  }

  // ---- hotspot table
  const visible = () => state.hotspots.filter((h) =>
    (state.filter === "all" || h.status === state.filter) && (!state.sev || h.severity === state.sev));

  function renderHotspots() {
    const rows = $("hotspot-rows");
    rows.innerHTML = "";
    const f = currentFlight();
    const vis = visible();
    const done = f && f.status === "done";
    $("table-bar").hidden = !done || state.hotspots.length === 0;
    $("hotspot-table").hidden = !done || vis.length === 0;
    $("hotspots-empty").hidden = !done || vis.length > 0;
    $("hotspots-empty").textContent = state.hotspots.length === 0 ? "No hotspots found on this flight." : "Nothing matches this filter.";
    $("sev-filter-note").innerHTML = state.sev ? `Showing ${SEV_NAME[state.sev].toLowerCase()} only. <a href="#" id="clear-sev">Show all severities</a>` : "";
    const clear = $("clear-sev");
    if (clear) clear.addEventListener("click", (e) => { e.preventDefault(); state.sev = null; renderSummary(); renderHotspots(); drawMap(false); });
    const top = Math.max(20, ...state.hotspots.map((h) => h.dt));
    vis.forEach((h) => {
      const tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.setAttribute("aria-selected", String(h.id === state.selected));
      const w = Math.max(4, Math.min(100, (h.dt / top) * 100));
      tr.innerHTML = `
        <td class="id">LG-${h.id}</td>
        <td><div class="heat"><b>+${h.dt.toFixed(1)} °C</b><span class="bar" title="${SEV_NAME[h.severity]}"><span class="${h.severity}" style="width:${w}%"></span></span></div></td>
        <td class="where-cell">${esc(whereText(h)) || "—"}<span class="coord">${h.lat.toFixed(6)}, ${h.lon.toFixed(6)}</span></td>
        <td><span class="status-pill ${h.status}">${STATUS_NAME[h.status]}</span></td>`;
      tr.addEventListener("click", () => select(h.id));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") select(h.id); });
      rows.appendChild(tr);
    });
  }

  // ---- detail
  function select(id) {
    state.selected = id;
    const h = state.hotspots.find((x) => x.id === id);
    if (!h) return;
    $("detail").hidden = false;
    $("d-title").textContent = `Hotspot LG-${h.id}`;
    $("d-dt").textContent = `+${h.dt.toFixed(1)} °C`;
    const sev = $("d-sev");
    sev.textContent = SEV_NAME[h.severity];
    sev.className = `sev ${h.severity}`;
    $("d-where").textContent = whereText(h) ? `${whereText(h)}${h.tower_dist_m != null ? `, ${Math.round(h.tower_dist_m)} m away` : ""}` : "";
    const hist = $("d-history");
    hist.hidden = h.prev_dt == null;
    if (h.prev_dt != null) {
      const diff = h.dt - h.prev_dt;
      hist.textContent = `Also found on an earlier flight at +${h.prev_dt.toFixed(1)} °C: now ${Math.abs(diff).toFixed(1)} °C ${diff >= 0 ? "hotter" : "cooler"}.`;
    }
    document.querySelectorAll(".status-buttons button").forEach((b) => b.classList.toggle("on", b.dataset.status === h.status));
    $("d-updated").textContent = h.updated_by && h.status !== "open" ? `Marked ${STATUS_NAME[h.status].toLowerCase()} by ${h.updated_by}, ${fmtDate(h.updated)}` : "";
    $("d-thermal").src = `/crops/${h.thermal_crop}`;
    $("d-colour-fig").hidden = !h.colour_crop;
    if (h.colour_crop) $("d-colour").src = `/crops/${h.colour_crop}`;
    $("d-context").src = `/crops/${h.thermal_crop.replace("_t.png", "_ctx.png")}`;
    $("d-photo").textContent = h.photo_name;
    $("d-seen").textContent = `Confirmed in ${h.photos} of the ${h.seen} photos that covered this spot.`;
    $("d-coords").textContent = `${h.lat.toFixed(7)}, ${h.lon.toFixed(7)}`;
    $("d-maps").href = `https://www.google.com/maps?q=${h.lat.toFixed(7)},${h.lon.toFixed(7)}`;
    $("d-oim").href = `https://openinframap.org/#17/${h.lat.toFixed(5)}/${h.lon.toFixed(5)}`;
    $("d-qr").src = `/qr/${h.id}.svg`;
    $("d-note").value = h.note || "";
    renderHotspots();
    drawMap(false);
    map.panTo([h.lat, h.lon]);
  }

  async function saveHotspot(changes) {
    const h = state.hotspots.find((x) => x.id === state.selected);
    if (!h) return;
    const updated = await api(`/api/hotspots/${h.id}`, { method: "PATCH", body: JSON.stringify(changes) });
    Object.assign(h, updated);
    renderSummary();
    select(h.id);
    loadFlightsOnce();
  }
  const loadFlightsOnce = async () => { state.flights = await api("/api/flights"); renderFlights(); };

  // ---- phones
  let pairTimer = null;
  async function openPhones() {
    $("phones-dialog").showModal();
    clearInterval(pairTimer);
    try {
      const p = await api("/api/pairing", { method: "POST" });
      $("pair-off").hidden = true;
      $("pair-on").hidden = false;
      $("pair-qr").innerHTML = p.qr;
      $("pair-code").textContent = p.code;
      $("pair-urls").innerHTML = `Address: ${p.urls.map((u) => `<code>${esc(u)}</code>`).join(" or ")}`;
      $("pair-hosted-note").textContent = state.status.hosted ? ", or has mobile data" : "";
      let left = p.expires_in;
      const tick = () => {
        $("pair-expiry").textContent = left > 0 ? `Code works once, for ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} more.` : "Code expired. Close and reopen for a new one.";
        left--;
      };
      tick();
      pairTimer = setInterval(() => { tick(); if (left % 5 === 0) loadDevices(); }, 1000);
    } catch (e) {
      $("pair-on").hidden = true;
      $("pair-off").hidden = false;
    }
    loadDevices();
  }
  async function loadDevices() {
    const list = await api("/api/devices").catch(() => []);
    $("device-list").innerHTML = list.length ? list.map((d) => `<li><span><b>${esc(d.name)}</b><br><span class="meta">Paired ${fmtDate(d.created)}${d.last_seen ? ` · last seen ${fmtDate(d.last_seen)}` : ""}</span></span>
      <button type="button" class="quiet small" data-unpair="${d.id}">Unpair</button></li>`).join("") : '<li class="meta">No phones paired yet.</li>';
    document.querySelectorAll("[data-unpair]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/devices/${b.dataset.unpair}`, { method: "DELETE" });
      loadDevices();
    }));
  }
  $("phones-dialog").addEventListener("close", () => clearInterval(pairTimer));

  // ---- towers
  async function loadTowerSources() {
    const list = await api("/api/towers").catch(() => []);
    $("tower-sources").innerHTML = list.length ? list.map((t) => `<li><span><b>${esc(t.source)}</b> · ${t.towers} towers</span>
      <button type="button" class="quiet small" data-tsrc="${esc(t.source)}">Remove</button></li>`).join("") : '<li class="meta">No tower lists imported.</li>';
    document.querySelectorAll("[data-tsrc]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/towers/${encodeURIComponent(b.dataset.tsrc)}`, { method: "DELETE" });
      loadTowerSources();
      if (state.flightId) openFlight(state.flightId, true);
    }));
  }
  $("towers-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = $("towers-file").files[0];
    if (!file) return;
    const data = new FormData();
    data.append("file", file);
    try {
      const r = await api("/api/towers", { method: "POST", body: data });
      $("towers-msg").textContent = `Imported ${r.towers} towers from ${r.source}. Hotspots have been relabelled.`;
      $("towers-file").value = "";
      loadTowerSources();
      if (state.flightId) openFlight(state.flightId, true);
    } catch (err) {
      $("towers-msg").textContent = err.message;
    }
  });

  // ---- events
  $("add-open").addEventListener("click", () => $("add-dialog").showModal());
  $("phones-open").addEventListener("click", openPhones);
  $("towers-open").addEventListener("click", () => { $("towers-msg").textContent = ""; loadTowerSources(); $("towers-dialog").showModal(); });
  document.querySelectorAll(".filters button").forEach((b) => b.addEventListener("click", () => {
    state.filter = b.dataset.filter;
    document.querySelectorAll(".filters button").forEach((x) => x.classList.toggle("on", x === b));
    renderHotspots();
    drawMap(false);
  }));
  document.querySelectorAll(".tile[data-sev]").forEach((t) => t.addEventListener("click", () => {
    state.sev = state.sev === t.dataset.sev ? null : t.dataset.sev;
    if (state.sev) {
      state.filter = "open";
      document.querySelectorAll(".filters button").forEach((x) => x.classList.toggle("on", x.dataset.filter === "open"));
    }
    renderSummary(); renderHotspots(); drawMap(false);
  }));
  document.querySelector(".tile[data-filter-status]").addEventListener("click", () => {
    state.sev = null;
    state.filter = "repaired";
    document.querySelectorAll(".filters button").forEach((x) => x.classList.toggle("on", x.dataset.filter === "repaired"));
    renderSummary(); renderHotspots(); drawMap(false);
  });
  document.querySelectorAll(".status-buttons button").forEach((b) =>
    b.addEventListener("click", () => saveHotspot({ status: b.dataset.status })));
  $("d-note").addEventListener("change", (e) => saveHotspot({ note: e.target.value }));
  $("detail-close").addEventListener("click", () => { $("detail").hidden = true; state.selected = null; renderHotspots(); drawMap(false); });
  $("d-copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("d-coords").textContent); $("d-copy").textContent = "Copied"; }
    catch { $("d-copy").textContent = "Select and copy"; }
    setTimeout(() => ($("d-copy").textContent = "Copy"), 1500);
  });
  $("reprocess").addEventListener("click", async () => {
    document.querySelector(".more").open = false;
    await api(`/api/flights/${state.flightId}/reprocess`, { method: "POST" });
    loadFlightsOnce();
  });
  $("power-load").addEventListener("click", async (e) => {
    e.target.textContent = "Loading power lines...";
    try {
      const r = await api(`/api/flights/${state.flightId}/power`, { method: "POST" });
      e.target.textContent = r.message;
      await openFlight(state.flightId, true);
    } catch (err) {
      e.target.textContent = err.message;
    }
    setTimeout(() => (e.target.textContent = "Load power lines from OpenStreetMap"), 6000);
  });
  $("import-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("import-path");
    try {
      const { id } = await api("/api/flights", { method: "POST", body: JSON.stringify({ path: input.value }) });
      input.value = "";
      $("add-dialog").close();
      await loadFlightsOnce();
      openFlight(id);
    } catch (err) {
      input.setCustomValidity(err.message);
      input.reportValidity();
      setTimeout(() => input.setCustomValidity(""), 3000);
    }
  });
  $("upload-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("upload-files");
    if (!input.files.length) return;
    const total = [...input.files].reduce((n, f) => n + f.size, 0);
    if (state.status && total > state.status.max_upload_mb * 1024 * 1024) {
      input.setCustomValidity(`The upload is larger than ${state.status.max_upload_mb} MB. Split the flight into smaller zips.`);
      input.reportValidity();
      setTimeout(() => input.setCustomValidity(""), 4000);
      return;
    }
    const data = new FormData();
    [...input.files].forEach((f) => data.append("files", f, f.webkitRelativePath || f.name));
    const xhr = new XMLHttpRequest();
    const progress = $("upload-progress");
    const button = $("upload-button");
    progress.hidden = false;
    button.disabled = true;
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) progress.textContent = `Uploading ${Math.round((ev.loaded / ev.total) * 100)}%`; };
    xhr.onload = async () => {
      button.disabled = false;
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status === 201) {
        progress.textContent = `Uploaded ${body.files} files. Processing has started.`;
        input.value = "";
        await loadFlightsOnce();
        openFlight(body.id);
        setTimeout(() => $("add-dialog").close(), 1200);
      } else {
        progress.textContent = body.error || `Upload failed (${xhr.status})`;
      }
    };
    xhr.onerror = () => { button.disabled = false; progress.textContent = "Upload failed: connection lost"; };
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("X-LineGuard", "1");
    xhr.send(data);
  });

  // ---- start
  api("/api/status").then((s) => {
    state.status = s;
    $("server-name").textContent = s.name;
    $("inbox-path").textContent = s.inbox;
    $(s.hosted ? "add-upload" : "add-local").hidden = false;
    setTiles(s.tiles, s.offline_tiles);
  });
  loadFlights();
})();
