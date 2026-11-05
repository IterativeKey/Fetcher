/*
 * Fetcher UI. Zero third-party assets - everything is in this file and
 * index.html. Talks to api/ (REST) and api/events (WebSocket). All paths are
 * relative so the UI also works behind a reverse-proxy path (e.g. QTS /fetcher).
 * The server requires FETCHER_API_TOKEN; the UI asks once and stores it.
 */
"use strict";

// ---- tiny DOM helpers ---------------------------------------------------------

const $ = (s, r = document) => r.querySelector(s);

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

// replaceChildren() that skips null/false (conditional children), like h().
function put(el, ...kids) {
  el.replaceChildren(...kids.flat().filter(c => c !== null && c !== undefined && c !== false));
}

const ICON = {
  pause: "M6 5h4v14H6zM14 5h4v14h-4z",
  play: "M7 4l13 8-13 8z",
  retry: "M12 5V2L7 6l5 4V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z",
  download: "M11 3h2v10l4-4 1.4 1.4L12 16.8 5.6 10.4 7 9l4 4zM5 19h14v2H5z",
  eye: "M12 5C6 5 2 12 2 12s4 7 10 7 10-7 10-7-4-7-10-7zm0 11a4 4 0 1 1 0-8 4 4 0 0 1 0 8z",
  more: "M5 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm7 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm7 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  star: "M12 2l3 7 7 .6-5.3 4.7 1.6 7.2L12 17.8 5.7 21.5l1.6-7.2L2 9.6 9 9z",
  gear: "M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.4 7.4 0 0 0-1.7-1L15 3h-4l-.3 2.9a7.4 7.4 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.4 7.4 0 0 0 1.7 1L11 21h4l.3-2.9a7.4 7.4 0 0 0 1.7-1l2.5 1 2-3.5zM12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z",
  plus: "M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z",
  trash: "M6 7h12l-1 14H7zM9 3h6l1 2h4v2H4V5h4z",
  copy: "M8 8h11v13H8zM5 3h11v3H7v11H5z",
  link: "M14 3h7v7h-2V6.4l-8.3 8.3-1.4-1.4L17.6 5H14zM5 5h6v2H7v10h10v-4h2v6H5z",
  stop: "M6 6h12v12H6z",
  x: "M6.4 5 12 10.6 17.6 5 19 6.4 13.4 12 19 17.6 17.6 19 12 13.4 6.4 19 5 17.6 10.6 12 5 6.4z",
  up: "M12 4l7 7h-4v9H9v-9H5z",
  down: "M12 20l-7-7h4V4h6v9h4z",
  edit: "M3 17.2V21h3.8L18 9.8 14.2 6zM20.7 7a1 1 0 0 0 0-1.4l-2.3-2.3a1 1 0 0 0-1.4 0l-1.8 1.8 3.8 3.8z",
  hide: "M2 4.3 3.3 3 21 20.7 19.7 22l-3.3-3.3A10.6 10.6 0 0 1 12 19C6 19 2 12 2 12a18 18 0 0 1 4.3-5.1zM12 5c6 0 10 7 10 7a18 18 0 0 1-2.9 3.9L8.4 5.3A10 10 0 0 1 12 5z",
  speed: "M12 4a10 10 0 0 0-8.7 15h17.4A10 10 0 0 0 12 4zm1 10.7a2 2 0 1 1-2.6-2.6l5.1-3.6z",
  hash: "M9 3h2l-.6 4h4l.6-4h2l-.6 4H20v2h-3.9l-.6 4H19v2h-3.1l-.6 4h-2l.6-4h-4l-.6 4h-2l.6-4H4v-2h3.9l.6-4H5V7h3.4zm1.1 6-.6 4h4l.6-4z",
  info: "M11 7h2v2h-2zm0 4h2v6h-2zm1-9a10 10 0 1 0 0 20 10 10 0 0 0 0-20z",
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "i");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", ICON[name]);
  svg.append(p);
  return svg;
}

// ---- preferences (per browser) ------------------------------------------------

const PREF_KEY = "fetcher_prefs";
const prefs = Object.assign(
  { tab: "all", sort: "added", showHidden: false, cat: "", notify: false, theme: "auto" },
  (() => { try { return JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { return {}; } })());
function savePrefs() { try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch {} }
function applyTheme() {
  if (prefs.theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = prefs.theme;
}
applyTheme();

// ---- auth + api -----------------------------------------------------------------

function storedToken() { try { return localStorage.getItem("fetcher_token") || ""; } catch { return ""; } }
function setToken(t) { try { localStorage.setItem("fetcher_token", t); } catch {} }

let loginOpen = false;
async function login(message) {
  if (loginOpen) return;
  loginOpen = true;
  const r = await dialog({
    title: "Sign in to Fetcher",
    text: message || "Enter this server's token (FETCHER_API_TOKEN in .env; setup.sh printed it).",
    fields: [{ name: "token", label: "Token", type: "password", value: "" }],
    ok: "Sign in", cancel: null,
  });
  loginOpen = false;
  if (r && r.token.trim()) { setToken(r.token.trim().replace(/^token:/, "")); reconnect(); }
  else login(message);
}

async function api(path, opts = {}) {
  const headers = { "X-Fetcher-Token": "token:" + storedToken(), ...(opts.headers || {}) };
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts = { ...opts, body: JSON.stringify(opts.json) };
  }
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { login("That token was not accepted. Try again."); throw new Error("not signed in"); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join("; ") : `HTTP ${res.status}`);
  }
  return body;
}

// ---- formatting -------------------------------------------------------------------

function fmtSize(n) {
  let v = Number(n) || 0;
  if (!v) return "0 B";
  const u = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}

function fmtDur(s) {
  s = Math.max(0, Math.round(s));
  const d = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${hh}h`;
  if (hh) return `${hh}h ${m}m`;
  if (m) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

function fmtAgo(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

const fmtDate = ts => ts ? new Date(ts * 1000).toLocaleString() : "";
const pct = j => j.total > 0 ? Math.min(100, Math.floor((j.done / j.total) * 100)) : 0;

function relPath(p) { return (p || "").replace(/^\/downloads\/?/, ""); }

function displayName(j) {
  if (j.name) return j.name;
  try { return decodeURIComponent(new URL(j.url).pathname.split("/").pop()) || new URL(j.url).hostname; }
  catch { return j.url; }
}

const VIEWABLE = /\.(png|jpe?g|gif|webp|avif|bmp|ico|mp4|webm|m4v|mov|ogv|mp3|m4a|aac|ogg|oga|opus|flac|wav|txt|log|md|csv)$/i;

const STATUS_LABEL = { active: "Downloading", waiting: "Queued", paused: "Paused", complete: "Done", error: "Failed", stopped: "Stopped" };

// ---- state --------------------------------------------------------------------------

let jobs = new Map();       // id -> job (history row)
let live = {};              // id -> {status, speed, connections, done, total}
let connected = true;       // false while the live connection to Fetcher is down
let lastMessage = 0;        // when the server last sent something (about every second)
let categories = [];
let settings = { speed_limit: 0, max_concurrent: 5 };
let stats = {};
const selected = new Set();
const expanded = new Set();
const rows = new Map();     // id -> row element
const hashing = new Set();  // ids whose SHA-256 is being computed
let lastStatus = new Map(); // id -> status, for "finished" notifications
let firstSnapshot = true;

function eff(j) {
  const l = live[j.id];
  if (!l) return { ...j, speed: 0, connections: 0 };
  return { ...j, status: l.status, speed: l.speed, connections: l.connections,
           done: l.done, total: l.total || j.total };
}

const TABS = [
  { key: "all", label: "All", test: () => true },
  { key: "downloading", label: "Downloading", test: j => j.status === "active" || j.status === "waiting" },
  { key: "paused", label: "Paused", test: j => j.status === "paused" },
  { key: "complete", label: "Completed", test: j => j.status === "complete" },
  { key: "failed", label: "Failed", test: j => j.status === "error" || j.status === "stopped" },
  { key: "favorites", label: "Favorites", test: j => !!j.favorite },
  { key: "connections", label: "Connections" },
];

function matchesSearch(j, q) {
  if (!q) return true;
  return [displayName(j), j.url, j.category, relPath(j.path)].join("\n").toLowerCase().includes(q);
}

function visibleJobs() {
  const tab = TABS.find(t => t.key === prefs.tab) || TABS[0];
  const q = $("#search").value.trim().toLowerCase();
  const list = [...jobs.values()].map(eff).filter(j =>
    (prefs.showHidden || !j.hidden) && (!prefs.cat || j.category === prefs.cat) &&
    tab.test(j) && matchesSearch(j, q));
  const order = { active: 0, waiting: 1, paused: 2, error: 3, stopped: 4, complete: 5 };
  const by = {
    "added": (a, b) => b.id - a.id,
    "added-asc": (a, b) => a.id - b.id,
    "name": (a, b) => displayName(a).localeCompare(displayName(b), undefined, { numeric: true }),
    "size": (a, b) => b.total - a.total,
    "progress": (a, b) => pct(b) - pct(a),
    "status": (a, b) => (order[a.status] - order[b.status]) || b.id - a.id,
  }[prefs.sort] || ((a, b) => b.id - a.id);
  return list.sort(by);
}

// ---- rendering ------------------------------------------------------------------------

function renderHeader() {
  const s = stats || {};
  const parts = [];
  if (!connected) parts.push(h("span", { class: "engine-down", text: "Reconnecting…" }));
  else if (s.engine === false) parts.push(h("span", { class: "engine-down", text: "Download engine unreachable" }));
  parts.push(h("span", {}, h("b", { text: `${fmtSize(s.speed || 0)}/s` }), ` · ${s.active || 0} active`));
  if (settings.speed_limit) parts.push(h("span", { class: "hide-sm", text: `limit ${fmtSize(settings.speed_limit)}/s` }));
  if (s.disk && s.disk.total) {
    const used = 100 - Math.round((s.disk.free / s.disk.total) * 100);
    parts.push(h("span", { class: "disk", title: `${fmtSize(s.disk.free)} free of ${fmtSize(s.disk.total)}` },
      h("span", { class: "bar" }, h("div", { class: "fill", style: `width:${used}%;transition:none` })),
      `${fmtSize(s.disk.free)} free`));
  }
  put($("#hstats"), parts);
  document.title = s.active ? `(${s.active}) ${fmtSize(s.speed)}/s · Fetcher` : "Fetcher";
}

function renderTabs() {
  const all = [...jobs.values()].map(eff).filter(j => (prefs.showHidden || !j.hidden) && (!prefs.cat || j.category === prefs.cat));
  $("#tabs").replaceChildren(...TABS.map(t => h("button", {
    class: prefs.tab === t.key ? "on" : "", type: "button", dataset: { tab: t.key },
  }, t.label, t.test ? h("span", { class: "n", text: String(all.filter(t.test).length) }) : null)));
  const hiddenN = [...jobs.values()].filter(j => j.hidden).length;
  $("#hiddenCount").textContent = hiddenN ? `(${hiddenN})` : "";
}

function renderCategories() {
  $("#cats").replaceChildren(...categories.map(c => h("option", { value: c })));
  const sel = $("#catFilter");
  const opts = [h("option", { value: "", text: "All folders" }),
    ...categories.map(c => h("option", { value: c, text: c }))];
  if (prefs.cat && !categories.includes(prefs.cat)) prefs.cat = "";
  sel.replaceChildren(...opts);
  sel.value = prefs.cat;
  sel.hidden = categories.length === 0;
}

function render() {
  const conns = prefs.tab === "connections";
  $("#conns").hidden = !conns;
  $("#list").hidden = conns;
  $("#toolbar").hidden = conns;
  renderTabs();
  renderHeader();
  if (conns) { $("#empty").hidden = true; $("#bulk").hidden = true; return; }

  const list = visibleJobs();
  const ids = new Set(list.map(j => j.id));
  for (const [id, el] of rows) if (!ids.has(id)) { el.remove(); rows.delete(id); }
  for (const id of [...selected]) if (!jobs.has(id)) selected.delete(id);
  const $list = $("#list");
  list.forEach((j, i) => {
    let el = rows.get(j.id);
    if (!el) { el = h("div", { class: "row", dataset: { id: j.id } }); rows.set(j.id, el); }
    fillRow(el, j);
    if ($list.children[i] !== el) $list.insertBefore(el, $list.children[i] || null);
  });

  const empty = $("#empty");
  empty.hidden = list.length > 0;
  if (!list.length) {
    empty.textContent = jobs.size === 0 ? "No downloads yet. Paste a link above to start."
      : "Nothing matches here." + ([...jobs.values()].some(j => j.hidden) && !prefs.showHidden ? " (Hidden downloads are not shown.)" : "");
  }
  const allSel = list.length > 0 && list.every(j => selected.has(j.id));
  $("#selAll").checked = allSel;
  $("#selAll").indeterminate = !allSel && list.some(j => selected.has(j.id));
  renderBulk();
}

// Update only what changes every second (progress, speed) without rebuilding rows.
function renderLive() {
  renderHeader();
  for (const id of Object.keys(live)) {
    const el = rows.get(Number(id));
    const j = jobs.get(Number(id));
    if (el && j) fillRow(el, eff(j));
  }
  // Countdowns to automatic retries.
  for (const [id, el] of rows) {
    const j = jobs.get(id);
    if (j && j.status === "error" && j.retry_at) fillRow(el, j);
  }
}

function statsLine(j) {
  const p = pct(j);
  const size = j.total ? `${fmtSize(j.done)} / ${fmtSize(j.total)} · ${p}%` : (j.done ? fmtSize(j.done) : "");
  switch (j.status) {
    case "active": {
      const left = j.total - j.done;
      const eta = j.speed && left > 0 ? `~${fmtDur(left / j.speed)} left` : "";
      return [j.speed ? `${fmtSize(j.speed)}/s` : "connecting…", size, j.connections ? `${j.connections} conn` : "", eta]
        .filter(Boolean).join(" · ");
    }
    case "complete": {
      const took = j.finished_at && j.added_at ? j.finished_at - j.added_at : 0;
      return [fmtSize(j.total), took > 1 ? `${fmtDur(took)} · avg ${fmtSize(j.total / took)}/s` : ""]
        .filter(Boolean).join(" · ");
    }
    default:
      return [size, j.speed_limit ? `limit ${fmtSize(j.speed_limit)}/s` : "", retryText(j)].filter(Boolean).join(" · ");
  }
}

function retryText(j) {
  if (j.status !== "error") return "";
  if (j.retry_at) {
    const left = j.retry_at - Date.now() / 1000;
    return left > 1 ? `auto-retry ${j.retries + 1} in ${fmtDur(left)}` : `auto-retry ${j.retries + 1} starting…`;
  }
  return j.retries ? `gave up after ${j.retries} automatic retr${j.retries === 1 ? "y" : "ies"}` : "";
}

function iconBtn(name, title, onclick, cls = "") {
  return h("button", { class: `btn ghost icon ${cls}`, type: "button", title, "aria-label": title, onclick }, icon(name));
}

function primaryActions(j) {
  const out = [];
  if (j.status === "active" || j.status === "waiting") out.push(iconBtn("pause", "Pause", () => act(j.id, "pause")));
  if (j.status === "paused") out.push(iconBtn("play", "Resume", () => act(j.id, "resume")));
  if (j.status === "error" || j.status === "stopped") out.push(iconBtn("retry", "Retry (resumes where it stopped)", () => act(j.id, "retry")));
  if (j.status === "complete" && !j.file_deleted) {
    out.push(iconBtn("download", "Save to this device", () => toBrowser(j.id, false)));
    if (VIEWABLE.test(j.name || "")) out.push(iconBtn("eye", "Open in a new tab", () => toBrowser(j.id, true)));
  }
  out.push(iconBtn("more", "More actions", (e) => openMenu(e.currentTarget, j.id)));
  return out;
}

function fillRow(el, j) {
  // Rebuild cheaply but keep focus/menus stable by key: rows are small.
  const key = [j.status, j.name, j.favorite, j.hidden, j.file_deleted, j.category, j.error, j.sha256,
               j.speed_limit, selected.has(j.id), expanded.has(j.id), hashing.has(j.id), j.path, j.total].join("|");
  el.dataset.status = j.status;
  el.classList.toggle("sel", selected.has(j.id));
  el.classList.toggle("hidden-job", !!j.hidden);
  if (el._key !== key) {
    el._key = key;
    const chipText = j.status === "complete" && j.file_deleted ? "File deleted" : STATUS_LABEL[j.status] || j.status;
    put(el,
      h("div", { class: "r1" },
        h("input", { type: "checkbox", checked: selected.has(j.id), "aria-label": "Select",
                     onchange: (e) => { e.target.checked ? selected.add(j.id) : selected.delete(j.id); render(); } }),
        h("button", { class: `star ${j.favorite ? "on" : ""}`, type: "button", title: j.favorite ? "Unfavorite" : "Favorite",
                      onclick: () => act(j.id, j.favorite ? "unfavorite" : "favorite") }, icon("star")),
        h("span", { class: `name ${j.file_deleted ? "gone" : ""}`, title: `${displayName(j)}\n${j.url}`,
                    text: displayName(j), onclick: () => toggleDetails(j.id) }),
        j.category ? h("span", { class: "chip cat", text: j.category, title: "Folder" }) : null,
        h("span", { class: `chip ${j.file_deleted ? "" : j.status}`, text: chipText }),
        h("span", { class: "acts" }, primaryActions(j))),
      j.status !== "complete" ? h("div", { class: "r2" }, h("div", { class: "bar" }, h("div", { class: "fill" }))) : null,
      h("div", { class: "r3" }, h("span", { class: "stats" }), h("span", { class: "when" })),
      j.error && j.status !== "complete" ? h("div", { class: "errline", text: errorText(j.error) }) : null,
      expanded.has(j.id) ? details(j) : null);
  }
  const fill = el.querySelector(".fill");
  if (fill) fill.style.width = pct(j) + "%";
  el.querySelector(".stats").textContent = statsLine(j);
  const when = el.querySelector(".when");
  when.textContent = j.status === "complete" ? `finished ${fmtAgo(j.finished_at)}` : `added ${fmtAgo(j.added_at)}`;
  when.title = fmtDate(j.status === "complete" ? j.finished_at : j.added_at);
}

function errorText(e) {
  return /proxy|403 Forbidden.*CONNECT/i.test(e)
    ? `${e} (blocked or unreachable through the egress gateway - see Connections)` : e;
}

function details(j) {
  const dl = h("dl", { class: "details" });
  const add = (k, ...v) => dl.append(h("dt", { text: k }), h("dd", {}, ...v));
  add("Link", h("span", { text: j.url }), h("button", { class: "linkbtn", type: "button", text: "copy", onclick: () => copy(j.url) }));
  if (j.path) add("Saved as", h("code", { text: relPath(j.path) }), j.file_deleted ? h("span", { class: "gone", text: "(deleted)" }) : null);
  add("Folder", j.category || "(main folder)");
  if (j.total) add("Size", `${fmtSize(j.total)} (${j.total.toLocaleString()} bytes)`);
  add("Added", fmtDate(j.added_at));
  if (j.finished_at) add("Finished", fmtDate(j.finished_at));
  if (j.status !== "complete")
    add("Speed limit", j.speed_limit ? `${fmtSize(j.speed_limit)}/s` : "none",
      h("button", { class: "linkbtn", type: "button", text: "change", onclick: () => jobSpeed(j) }));
  if (j.status === "complete" && !j.file_deleted)
    add("SHA-256", j.sha256 ? h("code", { text: j.sha256 }) : null,
      j.sha256 ? h("button", { class: "linkbtn", type: "button", text: "copy", onclick: () => copy(j.sha256) })
               : hashing.has(j.id) ? h("span", { text: "computing…" })
               : h("button", { class: "linkbtn", type: "button", text: "compute", onclick: () => checksum(j) }));
  if (j.error) add("Last error", errorText(j.error));
  add("ID", `#${j.id}${j.gid ? ` · engine gid ${j.gid}` : ""}`);
  return dl;
}

function toggleDetails(id) {
  expanded.has(id) ? expanded.delete(id) : expanded.add(id);
  render();
}

function renderBulk() {
  const bar = $("#bulk");
  const n = selected.size;
  bar.hidden = n === 0;
  if (!n) return;
  const ids = [...selected];
  const sel = ids.map(id => jobs.get(id)).filter(Boolean).map(eff);
  const any = f => sel.some(f);
  const b = (label, ic, fn, cls = "") => h("button", { class: `btn ${cls}`, type: "button", onclick: fn }, ic ? icon(ic) : null, label);
  put(bar,
    h("span", { class: "count", text: `${n} selected` }),
    any(j => j.status === "active" || j.status === "waiting") ? b("Pause", "pause", () => bulk("pause")) : null,
    any(j => j.status === "paused") ? b("Resume", "play", () => bulk("resume")) : null,
    any(j => j.status === "error" || j.status === "stopped") ? b("Retry", "retry", () => bulk("retry")) : null,
    any(j => !j.favorite) ? b("Favorite", "star", () => bulk("favorite")) : b("Unfavorite", "star", () => bulk("unfavorite")),
    any(j => !j.hidden) ? b("Hide", "hide", () => bulk("hide")) : b("Unhide", "eye", () => bulk("unhide")),
    b("Remove from list", "x", () => confirmRemove(ids, false)),
    any(j => !j.file_deleted && (j.path || j.status === "complete")) ? b("Delete files…", "trash", () => confirmRemove(ids, true), "danger") : null,
    h("span", { class: "spacer" }),
    b("Clear selection", null, () => { selected.clear(); render(); }, "ghost"));
}

// ---- actions ------------------------------------------------------------------------------

async function act(id, action) {
  try {
    const r = await api(`api/downloads/${id}/${action}`, { method: "POST" });
    if (r.note) toast(r.note, "warn");
  } catch (e) { toast(e.message, "bad"); }
}

async function bulk(action, ids = [...selected]) {
  try {
    const r = await api("api/bulk", { method: "POST", json: { ids, action } });
    if (r.errors.length) {
      toast(`${r.errors.length} of ${ids.length} failed: ` +
        r.errors.slice(0, 3).map(e => `${e.name}: ${e.error}`).join("; ") + (r.errors.length > 3 ? " …" : ""), "bad");
    }
    if (r.notes && r.notes.length) {
      toast(r.notes.slice(0, 3).join("; ") + (r.notes.length > 3 ? ` …and ${r.notes.length - 3} more` : ""), "warn");
    }
    return r;
  } catch (e) { toast(e.message, "bad"); }
}

async function confirmRemove(ids, withFiles) {
  const list = ids.map(id => jobs.get(id)).filter(Boolean);
  const names = list.slice(0, 6).map(j => "• " + displayName(j)).join("\n") + (list.length > 6 ? `\n…and ${list.length - 6} more` : "");
  const r = await dialog(withFiles ? {
    title: list.length === 1 ? "Delete this file?" : `Delete ${list.length} files?`,
    text: `This permanently deletes the downloaded file${list.length === 1 ? "" : "s"} from disk and removes ${list.length === 1 ? "it" : "them"} from the list. Unfinished downloads are stopped first. Only files Fetcher downloaded itself can be deleted.\n\n${names}`,
    ok: "Delete permanently", danger: true,
  } : {
    title: list.length === 1 ? "Remove from list?" : `Remove ${list.length} from the list?`,
    text: `Running downloads are stopped. Files on disk are kept.\n\n${names}`,
    ok: "Remove",
  });
  if (!r) return;
  const res = await bulk(withFiles ? "remove-and-delete" : "remove", list.map(j => j.id));
  if (res && res.ok) {
    ids.forEach(id => selected.delete(id));
    if (!(res.notes && res.notes.length)) toast(withFiles ? "Deleted." : "Removed from the list.", "ok");
  }
  render();
}

async function deleteFileKeepEntry(j) {
  const r = await dialog({
    title: "Delete the file, keep the entry?",
    text: `“${displayName(j)}” is deleted from disk. It stays in the list (marked deleted) so you can download it again later.`,
    ok: "Delete file", danger: true,
  });
  if (r) act(j.id, "delete-file");
}

async function toBrowser(id, inline) {
  // Open the tab synchronously (popup blockers), then point it at the link.
  const w = inline ? window.open("about:blank", "_blank") : null;
  try {
    const { url } = await api(`api/downloads/${id}/link?inline=${inline}`, { method: "POST" });
    if (w) { w.opener = null; w.location.href = new URL(url, location.href).href; return; }
    const a = h("a", { href: url, download: "" });
    document.body.append(a); a.click(); a.remove();
  } catch (e) { if (w) w.close(); toast(e.message, "bad"); }
}

async function renameJob(j) {
  const r = await dialog({
    title: "Rename file", fields: [{ name: "name", label: "New name", value: j.name, selectStem: true }], ok: "Rename",
  });
  if (!r || !r.name.trim() || r.name.trim() === j.name) return;
  try { await api(`api/downloads/${j.id}/rename`, { method: "POST", json: { name: r.name.trim() } }); toast("Renamed.", "ok"); }
  catch (e) { toast(e.message, "bad"); }
}

async function jobSpeed(j) {
  const r = await dialog({
    title: "Speed limit for this download",
    fields: [{ name: "kib", label: "KiB/s (0 = no limit)", type: "number", value: String(Math.round((j.speed_limit || 0) / 1024)), min: 0 }],
    ok: "Save",
  });
  if (!r) return;
  try { await api(`api/downloads/${j.id}`, { method: "PATCH", json: { speed_limit: Math.max(0, Number(r.kib) || 0) * 1024 } }); }
  catch (e) { toast(e.message, "bad"); }
}

// Reads the whole file on the NAS: big files take minutes, so show that it's
// running (in the details row) and say when it's done.
async function checksum(j) {
  if (hashing.has(j.id)) return;
  const name = displayName(j);
  hashing.add(j.id); expanded.add(j.id); render();
  toast(`Computing SHA-256 of ${name}… (large files can take a few minutes)`);
  try {
    const r = await api(`api/downloads/${j.id}/checksum`, { method: "POST" });
    const row = jobs.get(j.id);
    if (row) row.sha256 = r.sha256;
    toast(`SHA-256 ready: ${name}`);
  } catch (e) { toast(`SHA-256 of ${name} failed: ${e.message}`, "bad"); }
  finally { hashing.delete(j.id); render(); }
}

async function copy(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else {
      const t = h("textarea", { style: "position:fixed;opacity:0" });
      t.value = text; document.body.append(t); t.select(); document.execCommand("copy"); t.remove();
    }
    toast("Copied.", "ok");
  } catch { toast("Couldn't copy - select and copy it from the details instead.", "bad"); }
}

// ---- the "more" menu -------------------------------------------------------------------------

let menuEl = null;
function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }

function openMenu(anchor, id) {
  closeMenu();
  const j = eff(jobs.get(id));
  const it = (label, ic, fn, cls = "") => h("button", { type: "button", class: cls, onclick: () => { closeMenu(); fn(); } }, icon(ic), label);
  const items = [];
  const st = j.status;
  if (st === "active" || st === "waiting") items.push(it("Pause", "pause", () => act(id, "pause")));
  if (st === "paused") items.push(it("Resume", "play", () => act(id, "resume")));
  if (st === "waiting" || st === "paused") {
    items.push(it("Move to top of queue", "up", () => act(id, "top")));
    items.push(it("Move to bottom of queue", "down", () => act(id, "bottom")));
  }
  if (st === "error" || st === "stopped") items.push(it(j.retry_at ? "Retry now" : "Retry", "retry", () => act(id, "retry")));
  if (st === "error" && j.retry_at) items.push(it("Cancel automatic retry", "stop", () => act(id, "stop")));
  if (st === "active" || st === "waiting" || st === "paused") items.push(it("Stop (keep in list)", "stop", () => act(id, "stop")));
  if (st !== "complete") items.push(it("Speed limit…", "speed", () => jobSpeed(j)));
  if (st === "complete" && !j.file_deleted) {
    items.push(it("Save to this device", "download", () => toBrowser(id, false)));
    if (VIEWABLE.test(j.name || "")) items.push(it("Open in a new tab", "eye", () => toBrowser(id, true)));
    items.push(it("Rename…", "edit", () => renameJob(j)));
    if (!hashing.has(id))
      items.push(it(j.sha256 ? "Show SHA-256" : "Compute SHA-256", "hash", () => j.sha256 ? (expanded.add(id), render()) : checksum(j)));
  }
  if (st === "complete") items.push(it("Download again", "retry", () => act(id, "retry")));
  items.push(h("hr"));
  items.push(it("Copy link", "copy", () => copy(j.url)));
  items.push(it("Open original link", "link", () => window.open(j.url, "_blank", "noopener,noreferrer")));
  items.push(it("Details", "info", () => toggleDetails(id)));
  items.push(it(j.favorite ? "Unfavorite" : "Favorite", "star", () => act(id, j.favorite ? "unfavorite" : "favorite")));
  items.push(it(j.hidden ? "Unhide" : "Hide", j.hidden ? "eye" : "hide", () => act(id, j.hidden ? "unhide" : "hide")));
  items.push(h("hr"));
  items.push(it("Remove from list", "x", () => confirmRemove([id], false)));
  if (!j.file_deleted && (j.path || st === "complete")) {
    if (st === "complete") items.push(it("Delete file (keep entry)…", "trash", () => deleteFileKeepEntry(j), "danger"));
    items.push(it("Delete file and remove…", "trash", () => confirmRemove([id], true), "danger"));
  }
  menuEl = h("div", { class: "menu", role: "menu" }, items);
  document.body.append(menuEl);
  const r = anchor.getBoundingClientRect(), m = menuEl.getBoundingClientRect();
  const top = r.bottom + 4 + m.height > innerHeight ? Math.max(8, r.top - m.height - 4) : r.bottom + 4;
  menuEl.style.top = `${top}px`;
  menuEl.style.left = `${Math.max(8, Math.min(r.right - m.width, innerWidth - m.width - 8))}px`;
}

document.addEventListener("click", (e) => {
  if (menuEl && !menuEl.contains(e.target) && !e.target.closest(".acts")) closeMenu();
});
addEventListener("resize", closeMenu);
addEventListener("scroll", closeMenu, { passive: true });

// ---- dialogs & toasts ------------------------------------------------------------------------

// dialog({title, text, fields:[{name,label,type,value,options,min,max,selectStem,help}], ok, cancel, danger})
// -> Promise<object|null> with field values (checkboxes as booleans), null on cancel.
let dialogBusy = Promise.resolve();
function dialog(opts) {
  const run = () => new Promise((resolve) => {
    const dlg = $("#dlg"), form = $("#dlgForm");
    const fields = (opts.fields || []).map(f => {
      let input;
      if (f.type === "select") input = h("select", { name: f.name }, f.options.map(([v, t]) => h("option", { value: v, text: t })));
      else if (f.type === "checkbox") input = h("input", { type: "checkbox", name: f.name, checked: !!f.value });
      else input = h("input", { type: f.type || "text", name: f.name, value: f.value ?? "", min: f.min, max: f.max, autocomplete: "off", spellcheck: "false" });
      if (f.type === "select") input.value = f.value;
      return f.type === "checkbox"
        ? h("label", { class: "check field", style: "flex-direction:row" }, input, f.label)
        : h("label", { class: "field" }, h("span", { text: f.label }), input, f.help ? h("small", { class: "n", text: f.help }) : null);
    });
    const text = opts.text ? h("p", { style: "white-space:pre-line", text: opts.text }) : null;
    put(form,
      h("h2", { text: opts.title }), text, ...fields, ...(opts.extra || []),
      h("div", { class: "btns", style: "flex-direction:row-reverse;justify-content:flex-start" },
        h("button", { class: `btn ${opts.danger ? "danger" : "primary"}`, value: "ok", text: opts.ok || "OK" }),
        opts.cancel === null ? null : h("button", { class: "btn", value: "cancel", text: opts.cancel || "Cancel", formnovalidate: true })));
    dlg.returnValue = "";
    dlg.onclose = () => {
      if (dlg.returnValue !== "ok") return resolve(null);
      const out = {};
      for (const f of opts.fields || []) {
        const el = form.elements[f.name];
        out[f.name] = f.type === "checkbox" ? el.checked : el.value;
      }
      resolve(out);
    };
    dlg.oncancel = (e) => { if (opts.cancel === null) e.preventDefault(); };
    dlg.showModal();
    const first = form.querySelector("input, select");
    if (first) {
      first.focus();
      const f0 = (opts.fields || [])[0];
      if (f0 && f0.selectStem && first.value.includes(".")) first.setSelectionRange(0, first.value.lastIndexOf("."));
      else if (first.select) first.select();
    }
  });
  dialogBusy = dialogBusy.then(run, run);
  return dialogBusy;
}

function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}`, text: msg, role: kind === "bad" ? "alert" : "status" });
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "bad" || kind === "warn" ? 9000 : 3500);
}

// ---- settings ---------------------------------------------------------------------------------

async function openSettings() {
  let version = "", app = "";
  try {
    const hl = await api("api/health");
    version = hl.aria2_version;
    app = `Fetcher ${hl.version}, built ${hl.build}. `;
  } catch {}
  const r = await dialog({
    title: "Settings",
    fields: [
      { name: "speed", label: "Overall speed limit, KiB/s (0 = no limit)", type: "number", min: 0,
        value: String(Math.round(settings.speed_limit / 1024)) },
      { name: "conc", label: "Downloads at the same time", type: "number", min: 1, max: 20, value: String(settings.max_concurrent) },
      { name: "theme", label: "Theme (this browser)", type: "select", value: prefs.theme,
        options: [["auto", "Match system"], ["light", "Light"], ["dark", "Dark"]] },
      { name: "notify", label: "Notify me when a download finishes (this browser)", type: "checkbox", value: prefs.notify },
    ],
    extra: [
      h("p", { style: "font-size:12px", text: `${app}Download engine: aria2 ${version || "unreachable"}. Desktop notifications need HTTPS or localhost; otherwise a message appears in the page.` }),
      h("button", { class: "btn", type: "button", text: "Sign out of this browser",
                    onclick: () => { setToken(""); $("#dlg").close(); location.reload(); } }),
    ],
    ok: "Save",
  });
  if (!r) return;
  prefs.theme = r.theme; prefs.notify = r.notify; savePrefs(); applyTheme();
  if (prefs.notify && "Notification" in window && window.isSecureContext && Notification.permission === "default") {
    Notification.requestPermission();
  }
  try {
    settings = await api("api/settings", { method: "PUT",
      json: { speed_limit: Math.max(0, Number(r.speed) || 0) * 1024, max_concurrent: Math.min(20, Math.max(1, Number(r.conc) || 5)) } });
    renderHeader();
  } catch (e) { toast(e.message, "bad"); }
}

function notifyFinished(j) {
  if (!prefs.notify) return;
  const text = `Finished: ${displayName(j)}`;
  if ("Notification" in window && window.isSecureContext && Notification.permission === "granted") {
    new Notification("Fetcher", { body: text });
  } else toast(text, "ok");
}

// ---- connection log ---------------------------------------------------------------------------

function fmtTime(ts) {
  const d = new Date(ts), p = n => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function loadConnections() {
  const { events } = await api("api/connections?limit=500");
  $("#conns tbody").replaceChildren(...events.reverse().map(e => h("tr", { class: e.event },
    h("td", { class: "nw", text: fmtTime(e.ts) }),
    h("td", { class: "ev nw", text: e.event }),
    h("td", { text: e.target || "" }),
    h("td", { class: "nw", text: e.ip || "" }),
    h("td", { class: "nw", text: e.bytes_in === undefined ? "" : `↓ ${fmtSize(e.bytes_in)} · ↑ ${fmtSize(e.bytes_out)} · ${e.secs}s` }),
    h("td", { text: [e.status ? `HTTP ${e.status}` : "", e.url || "", e.reason || ""].filter(Boolean).join(" · ") }))));
}

setInterval(() => {
  if (prefs.tab === "connections" && !document.hidden) loadConnections().catch(() => {});
}, 3000);

// ---- live updates ------------------------------------------------------------------------------

function onFull(d) {
  const next = new Map(d.jobs.map(j => [j.id, j]));
  if (!firstSnapshot) {
    for (const j of next.values()) {
      const before = lastStatus.get(j.id);
      if (j.status === "complete" && before && before !== "complete") notifyFinished(j);
    }
  }
  lastStatus = new Map([...next.values()].map(j => [j.id, j.status]));
  firstSnapshot = false;
  jobs = next;
  live = d.live || {};
  stats = d.stats || {};
  settings = d.settings || settings;
  if (d.app) {
    const v = $("#ver");
    v.textContent = `v${d.app.version}`;
    v.title = `Fetcher ${d.app.version}, built ${d.app.build}`;
  }
  const catsChanged = JSON.stringify(categories) !== JSON.stringify(d.categories || []);
  categories = d.categories || [];
  if (catsChanged) renderCategories();
  render();
}

let ws = null;
function connect() {
  if (!storedToken()) { login(); return; }
  const url = new URL("api/events", location.href);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const sock = new WebSocket(url);
  ws = sock;
  // The token goes in the first message, never in the URL (URLs get logged).
  sock.onopen = () => { lastMessage = Date.now(); sock.send("token:" + storedToken()); };
  sock.onmessage = (m) => {
    lastMessage = Date.now();
    if (!connected) { connected = true; renderHeader(); }
    const d = JSON.parse(m.data);
    if (d.type === "full") onFull(d);
    else if (d.type === "live") { live = d.live || {}; stats = d.stats || stats; renderLive(); }
  };
  sock.onclose = (e) => {
    if (ws !== sock) return;
    if (e.code === 4401) { ws = null; login("That token was not accepted. Try again."); return; }
    connected = false;
    renderHeader();
    setTimeout(connect, 2000);
  };
}
function reconnect() { const old = ws; ws = null; if (old) old.close(); connect(); }

setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping"); }, 20000);
// A connection can die without closing (Wi-Fi switch, sleeping laptop, a
// proxy dropping it): if nothing arrived for a while, start a fresh one.
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN && Date.now() - lastMessage > 15000) reconnect();
}, 5000);

// ---- add form -----------------------------------------------------------------------------------

const $add = $("#add");
$add.querySelector(".go").append(icon("plus"), "Add");

function parseUrls(text) {
  return [...new Set(text.split(/\s+/).map(s => s.trim()).filter(Boolean))];
}

$add.onsubmit = async (e) => {
  e.preventDefault();
  const urls = parseUrls($add.urls.value);
  if (!urls.length) return;
  const btn = $add.querySelector(".go");
  btn.disabled = true;
  try {
    const { results } = await api("api/downloads", { method: "POST",
      json: { urls, category: $add.category.value.trim(), paused: $add.paused.checked } });
    const bad = results.filter(r => !r.ok);
    const ok = results.length - bad.length;
    if (ok) toast(`Added ${ok} download${ok === 1 ? "" : "s"}.`, "ok");
    for (const r of bad.slice(0, 5)) toast(`${r.url}\n${r.error}`, "bad");
    if (bad.length > 5) toast(`…and ${bad.length - 5} more failed.`, "bad");
    // Keep the failed ones in the box so they can be fixed and re-added.
    $add.urls.value = bad.map(r => r.url).join("\n");
  } catch (err) { toast(err.message, "bad"); }
  finally { btn.disabled = false; updateHint(); }
};

function updateHint() {
  const n = parseUrls($add.urls.value).length;
  $("#addHint").textContent = n > 1 ? `${n} links` : "";
}
$add.urls.addEventListener("input", updateHint);
$add.urls.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $add.requestSubmit(); }
});

function appendLinks(text) {
  const links = (text || "").match(/https?:\/\/[^\s"'<>]+/g);
  if (!links) return false;
  const cur = $add.urls.value.trim();
  $add.urls.value = (cur ? cur + "\n" : "") + links.join("\n");
  $add.urls.focus();
  updateHint();
  return true;
}

// Drop links anywhere on the page; paste them anywhere that isn't a text field.
document.addEventListener("dragover", (e) => { e.preventDefault(); $add.classList.add("drag"); });
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) $add.classList.remove("drag"); });
document.addEventListener("drop", (e) => {
  e.preventDefault();
  $add.classList.remove("drag");
  appendLinks(e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain"));
});
document.addEventListener("paste", (e) => {
  if (e.target.closest("input, textarea, select")) return;
  if (appendLinks(e.clipboardData.getData("text"))) e.preventDefault();
});

// ---- toolbar & keys ---------------------------------------------------------------------------

$("#tabs").onclick = (e) => {
  const b = e.target.closest("button[data-tab]");
  if (!b) return;
  prefs.tab = b.dataset.tab; savePrefs();
  render();
  if (prefs.tab === "connections") loadConnections().catch(err => toast(err.message, "bad"));
};
$("#search").oninput = () => render();
$("#sort").value = prefs.sort;
$("#sort").onchange = (e) => { prefs.sort = e.target.value; savePrefs(); render(); };
$("#catFilter").onchange = (e) => { prefs.cat = e.target.value; savePrefs(); render(); };
$("#showHidden").checked = prefs.showHidden;
$("#showHidden").onchange = (e) => { prefs.showHidden = e.target.checked; savePrefs(); render(); };
$("#selAll").onchange = (e) => {
  const ids = visibleJobs().map(j => j.id);
  if (e.target.checked) ids.forEach(id => selected.add(id)); else ids.forEach(id => selected.delete(id));
  render();
};
$("#clearDone").onclick = async () => {
  const done = [...jobs.values()].filter(j => j.status === "complete" && !j.favorite);
  if (!done.length) { toast("No completed downloads to clear (favorites are always kept)."); return; }
  const r = await dialog({ title: `Clear ${done.length} completed?`,
    text: "They're removed from the list; the files stay on disk. Favorites are kept.", ok: "Clear" });
  if (r) { await bulk("remove", done.map(j => j.id)); toast("Cleared.", "ok"); }
};

const $pauseAll = $("#pauseAll"), $resumeAll = $("#resumeAll"), $settings = $("#openSettings");
$pauseAll.append(icon("pause"), h("span", { class: "hide-sm", text: "Pause all" }));
$resumeAll.append(icon("play"), h("span", { class: "hide-sm", text: "Resume all" }));
$settings.append(icon("gear"));
$pauseAll.onclick = () => api("api/global/pause", { method: "POST" }).catch(e => toast(e.message, "bad"));
$resumeAll.onclick = () => api("api/global/resume", { method: "POST" }).catch(e => toast(e.message, "bad"));
$settings.onclick = openSettings;

document.addEventListener("keydown", (e) => {
  const typing = e.target.closest("input, textarea, select, dialog");
  if (e.key === "Escape") {
    if (menuEl) { closeMenu(); return; }
    if (!typing && selected.size) { selected.clear(); render(); }
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "/") { e.preventDefault(); $("#search").focus(); }
  else if (e.key === "n") { e.preventDefault(); $add.urls.focus(); }
  else if (e.key === "Delete" && selected.size) confirmRemove([...selected], false);
});

// Relative times ("3m ago") stay current.
setInterval(() => { if (!document.hidden) for (const [id, el] of rows) { const j = jobs.get(id); if (j) fillRow(el, eff(j)); } }, 30000);

renderCategories();
render();
connect();
