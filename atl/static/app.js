// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 D-LAB-5, Atelier-5
//
// app.js — atl-ide's page, in the D-LAB-5 app shell as digitalhome-twin-edge-WormBed-5 uses it.
// core.js has already wired the (hidden) header; window.core offers api(), dialog(), toast() and friends.
//
// v0.1, shell first: the rail, tabs, theme, language and the Table screen's layout. The
// live parts (camera, sensors, behaviour, acts) come with the gateway (step 5) and the
// simulation routes (step 6); until then the page says what will appear.

"use strict";

const $ = (sel) => document.querySelector(sel);
const S = { tab: "", lifted: false, behaviour: "none" };

/* The page in the person's language (i18n.py): the English text is the key, `{name}` a value filled in. */
const I18N = { lang: "en", catalog: {} };
function tr(text, values) {
  let out = (text && I18N.catalog[text]) || text || "";
  if (values) for (const [k, v] of Object.entries(values)) out = out.split(`{${k}}`).join(String(v));
  return out;
}
Object.assign(I18N, window.I18N_BOOT || {});

// The page's own text and the template's: every text node and title, label and alt that is exactly an English
// text in the catalog. Whitespace inside is folded, as the catalog keys are.
const I18N_ATTRS = ["title", "aria-label", "alt", "placeholder"];
function translateDom(root) {
  if (I18N.lang === "en" || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const key = n.nodeValue.replace(/\s+/g, " ").trim();
    if (key && I18N.catalog[key]) n.nodeValue = n.nodeValue.replace(/\S[\s\S]*\S|\S/, I18N.catalog[key]);
  }
  const els = root.querySelectorAll ? [root, ...root.querySelectorAll("[title],[aria-label],[alt],[placeholder]")] : [];
  for (const el of els) for (const a of I18N_ATTRS) {
    const v = el.getAttribute && el.getAttribute(a);
    if (v && I18N.catalog[v.trim()]) el.setAttribute(a, I18N.catalog[v.trim()]);
  }
}
document.documentElement.lang = I18N.lang;

// The language switch: a cookie the server reads too, then the page again in that language.
document.querySelectorAll("#lang-seg [data-lang]").forEach((b) => {
  const on = b.dataset.lang === I18N.lang;
  b.classList.toggle("app-seg__option--on", on);
  b.setAttribute("aria-pressed", String(on));
  b.addEventListener("click", () => {
    document.cookie = `lang=${b.dataset.lang}; path=/; max-age=31536000; samesite=lax`;
    location.reload();
  });
});

/* --------------------------------------------------------------- the robot -- */
// The six built-in behaviours, as atl-bot-thymio's behaviours.py names and colours them (EN first).
const BEHAVIOURS = [
  { id: "friendly", name: "Friendly", rgb: [0, 1, 0] },
  { id: "explorer", name: "Explorer", rgb: [1, 1, 0] },
  { id: "fearful", name: "Fearful", rgb: [1, 0, 0] },
  { id: "inspector", name: "Inspector", rgb: [0, 0.8, 1] },
  { id: "attentive", name: "Attentive", rgb: [0, 0, 1] },
  { id: "obedient", name: "Obedient", rgb: [1, 0, 0.6] },
];
const rgb = (c) => `rgb(${c.map((v) => Math.round(v * 255)).join(" ")})`;

$("#behaviours").innerHTML = BEHAVIOURS.map((b) =>
  `<button type="button" class="behaviour" data-behaviour="${b.id}" aria-pressed="false" disabled>`
  + `<span class="behaviour__swatch" style="background:${rgb(b.rgb)}"></span><span>${core.esc(tr(b.name))}</span></button>`).join("")
  + `<button type="button" class="behaviour" data-behaviour="none" aria-pressed="true" disabled><span class="behaviour__swatch"></span><span>${core.esc(tr("None"))}</span></button>`;

// The Thymio from above (SVG units ≈ mm): 5 front bars on the bumper's arc, 2 rear, 2 ground dots under the front.
const PROX = [[-62, -68, -40], [-34, -84, -18], [0, -88, 0], [34, -84, 18], [62, -68, 40], [-32, 60, 180], [32, 60, 180]];
const BAR_LEN = 30;
$("#bars").innerHTML = PROX.map(([x, y, a], i) => `
  <g transform="translate(${x} ${y}) rotate(${a})">
    <rect class="bar-bg" x="-5" y="${-BAR_LEN}" width="10" height="${BAR_LEN}" rx="2"/>
    <rect class="bar" id="bar-${i}" x="-5" y="0" width="10" height="0" rx="2"/>
    <text class="label" x="0" y="${-BAR_LEN - 4}" text-anchor="middle">${i}</text>
  </g>`).join("");
$("#grounds").innerHTML = [[-12, -62], [12, -62]].map(([x, y], i) =>
  `<circle class="ground" id="ground-${i}" cx="${x}" cy="${y}" r="7"/><text class="label" x="${x}" y="${y + 18}" text-anchor="middle">g${i}</text>`).join("");

// What the sensors read: bar length for the 7 horizontal values (raw, 0..4300), grey for the 2 ground values (0..1023).
function drawSensors(prox, ground, led) {
  prox.forEach((v, i) => {
    const h = Math.max(0, Math.min(1, v / 4300)) * BAR_LEN;
    const bar = $(`#bar-${i}`);
    bar.setAttribute("y", String(-h));
    bar.setAttribute("height", String(h));
  });
  ground.forEach((v, i) => {
    const dot = $(`#ground-${i}`);
    dot.classList.toggle("ground--none", v == null);
    if (v == null) { dot.style.fill = ""; return; }
    const g = Math.round(Math.max(0, Math.min(1, v / 1023)) * 255);
    dot.style.fill = `rgb(${g} ${g} ${g})`;
  });
  $("#led-top").setAttribute("fill", led && led.some((c) => c > 0) ? rgb(led) : "none");
}
drawSensors([0, 0, 0, 0, 0, 0, 0], [null, null], null);      // no readings yet

// The names stay hidden until the facilitators decide (the spec: nothing is named in advance).
function namesShown(on) {
  document.body.classList.toggle("names-off", !on);
  $("#chk-names").checked = on;
  try { localStorage.setItem("atl-ide-names", on ? "on" : "off"); } catch (_) { /* private window */ }
}
$("#chk-names").addEventListener("change", (e) => namesShown(e.target.checked));
{
  let saved = null;
  try { saved = localStorage.getItem("atl-ide-names"); } catch (_) { /* private window */ }
  namesShown(saved === "on");
}

/* ------------------------------------------------------------------ shell -- */
// The rail's own buttons call core's (its header stays in the page, hidden).

const TABS = ["table", "scene", "program", "connections", "chat"];

function showTab(name) {
  const tab = TABS.includes(name) ? name : "table";
  S.tab = tab;
  for (const t of TABS) $(`#tab-${t}`).hidden = t !== tab;
  document.querySelectorAll(".app-rail__item.tab").forEach((a) => {
    const on = a.dataset.tab === tab;
    a.classList.toggle("app-rail__item--on", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

function railOpen(open, remember = false) {
  $("#rail").classList.toggle("app-rail--closed", !open);
  $("#rail-toggle").setAttribute("aria-expanded", String(open));
  $("#rail-toggle").setAttribute("aria-label", open ? tr("Hide menu") : tr("Show menu"));
  if (remember) try { localStorage.setItem("atl-ide-rail", open ? "open" : "closed"); } catch (_) { /* private window */ }
}

function shownTheme() {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function markTheme() {
  const now = shownTheme();
  document.querySelectorAll("#theme-seg [data-theme-pick]").forEach((b) => {
    b.classList.toggle("app-seg__option--on", b.dataset.themePick === now);
    b.setAttribute("aria-pressed", String(b.dataset.themePick === now));
  });
}

/* ------------------------------------------------------------- simulation -- */
// The virtual table (sim.py): start, a checklist while it comes up, then the robot live at 10 Hz.

const say = (err) => core.toast((err.errors || [String(err)]).join("; "), true);
async function post(path, body) {
  try { return await core.api("POST", path, body || {}); } catch (err) { say(err); return null; }
}
const robot = (action, body) => post(`/api/robot/${action}`, body);

const STEP_STATES = ["todo", "now", "done"];
function drawSim(s) {
  S.phase = s.phase;
  const running = s.phase === "running", busy = s.phase === "starting" || s.phase === "stopping";
  $("#sim-status").textContent = tr({
    stopped: "The simulation is not running.", starting: "Starting the simulation…", running: "The simulation is running.",
    stopping: "Stopping the simulation…", failed: "The simulation did not start." }[s.phase] || s.phase);
  const hint = $("#sim-hint");
  hint.classList.toggle("sim-error", s.phase === "failed");
  hint.textContent = s.phase === "failed" ? tr(s.error)
    : s.missing && s.missing.length && s.phase === "stopped" ? s.missing.map((m) => tr(m)).join(" · ")
    : running ? tr("Move the box in the Webots window and watch the sensors.")
    : s.phase === "stopped" ? (s.error ? tr(s.error) : tr("Start it: Webots opens the table with one Thymio II.")) : "";
  $("#btn-start").hidden = running || busy;
  $("#btn-start").disabled = !!(s.missing && s.missing.length);
  $("#btn-stop-sim").hidden = !(running || s.phase === "starting");
  $("#btn-reset").disabled = !running;
  $("#sim-steps").hidden = !(s.phase === "starting" || s.phase === "failed");
  document.querySelectorAll("#sim-steps li").forEach((li) => {
    for (const st of STEP_STATES) li.classList.toggle(st, (s.steps || {})[li.dataset.step] === st);
  });
  $("#sim-log").hidden = !(s.phase === "failed" && s.log && s.log.length);
  $("#sim-log-text").textContent = (s.log || []).join("\n");
  $("#badge-sim").hidden = !running;
  $("#dot-table").hidden = !running;
  document.querySelectorAll("#behaviours .behaviour, #touch button, [data-clap], #btn-lift")
    .forEach((b) => { b.disabled = !running; });
  document.querySelectorAll("#pad button").forEach((b) => { b.disabled = !running || S.behaviour !== "none"; });
  if (running && !S.camera) {
    S.camera = true;
    $("#overview").innerHTML = `<img src="/api/robot/camera.mjpg" alt="${core.esc(tr("The table seen from above, live"))}">`;
  } else if (!running && S.camera) {
    S.camera = false;
    $("#overview").innerHTML = `<p class="empty">${core.esc(tr("The camera above the table shows here once the simulation runs."))}</p>`;
    drawSensors([0, 0, 0, 0, 0, 0, 0], [null, null], null);
    $("#sensor-values").textContent = tr("No readings yet.");
  }
}
async function pollSim() {
  try { drawSim(await core.api("GET", "/api/sim")); } catch (_) { /* the server restarts */ }
}
$("#btn-start").addEventListener("click", async () => { if (await post("/api/sim/start", { gui: true })) pollSim(); });
$("#btn-stop-sim").addEventListener("click", async () => { await post("/api/sim/stop"); pollSim(); });
$("#btn-reset").addEventListener("click", () => robot("reset"));
setInterval(pollSim, 1000);
pollSim();

/* the robot live: sensors, plots, behaviour, E-stop */
const PLOT_LEN = 120;                                    // 12 s at 10 Hz
const PLOTS = { prox: [], ground: [], acc: [], wheels: [] };
const PLOT_RANGE = { prox: [0, 4300], ground: [0, 1023], acc: [-12, 12], wheels: [-10, 10] };
let plotsPaused = false;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function drawPlot(id, rows) {
  const cv = $(`#plot-${id}`), g = cv.getContext("2d");
  const [lo, hi] = PLOT_RANGE[id], W = cv.width, H = cv.height;
  g.clearRect(0, 0, W, H);
  if (!rows.length) return;
  const colours = [1, 2, 3, 4, 5, 6, 1].map((k) => css(`--app-cat-${k}`));
  for (let k = 0; k < rows[0].length; k++) {
    g.beginPath();
    g.strokeStyle = colours[k];
    g.lineWidth = 1.4;
    rows.forEach((r, i) => {
      const x = (i / (PLOT_LEN - 1)) * W, y = H - ((Math.max(lo, Math.min(hi, r[k])) - lo) / (hi - lo)) * (H - 4) - 2;
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    });
    g.stroke();
  }
}
$("#btn-pause").addEventListener("click", (e) => {
  plotsPaused = !plotsPaused;
  e.target.setAttribute("aria-pressed", String(plotsPaused));
  e.target.textContent = tr(plotsPaused ? "Resume the plots" : "Pause the plots");
});

const fmt = (xs, d = 0) => (xs || []).map((v) => Number(v).toFixed(d)).join(" ");
function drawRobot(r) {
  S.behaviour = (r.behaviour && r.behaviour.behaviour) || "none";
  drawSensors(r.prox || [0, 0, 0, 0, 0, 0, 0], r.ground || [null, null], r.behaviour && S.behaviour !== "none" ? r.behaviour.colour : r.led);
  const names = !document.body.classList.contains("names-off");
  const label = (plain, name) => tr(names ? name : plain);
  $("#sensor-values").innerHTML = [
    `${core.esc(label("around", "proximity"))}: ${fmt(r.prox)}`,
    `${core.esc(label("underneath", "ground"))}: ${fmt(r.ground)}`,
    `${core.esc(label("tilt and shake", "accelerometer"))}: ${fmt(r.imu, 2)} m/s²`,
    `${core.esc(label("wheels", "wheel encoders"))}: ${fmt(r.wheels, 2)} rad/s`].join("<br>");
  if (!plotsPaused) {
    const push = (k, v) => { if (v) { PLOTS[k].push(v); if (PLOTS[k].length > PLOT_LEN) PLOTS[k].shift(); } };
    push("prox", r.prox); push("ground", r.ground); push("acc", r.imu); push("wheels", r.wheels);
    for (const k of Object.keys(PLOTS)) drawPlot(k, PLOTS[k]);
  }
  document.querySelectorAll("#behaviours .behaviour").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.behaviour === S.behaviour)));
  const doing = r.behaviour && S.behaviour !== "none" ? r.behaviour.doing : "";
  const name = (BEHAVIOURS.find((b) => b.id === S.behaviour) || {}).name;
  $("#behaviour-doing").textContent = doing ? `${tr(name)}: ${tr(doing)}` : "";
  $("#strip-behaviour").textContent = name ? `${tr(name)}${doing ? " · " + tr(doing) : ""}` : "";
  const byHand = S.behaviour === "none";
  document.querySelectorAll("#pad button").forEach((b) => {
    b.disabled = !byHand;
    b.title = byHand ? "" : tr("A behaviour drives the robot: stop it to drive by hand");
  });
  S.estop = !!r.estop;
  $("#badge-estop").hidden = !S.estop;
  $("#btn-estop").textContent = tr(S.estop ? "Release the E-stop" : "E-stop");
  S.lifted = !!r.lifted;
  $("#btn-lift").textContent = tr(S.lifted ? "Put it down" : "Lift the robot");
  $("#btn-lift").setAttribute("aria-pressed", String(S.lifted));
}
async function pollRobot() {
  if (S.phase !== "running" || S.tab !== "table") return;
  try { drawRobot(await core.api("GET", "/api/robot/state")); } catch (_) { /* a missed beat */ }
}
setInterval(pollRobot, 100);

document.querySelectorAll("#behaviours .behaviour").forEach((b) =>
  b.addEventListener("click", () => robot("behaviour", { name: b.dataset.behaviour })));
document.querySelectorAll("#touch [data-button]").forEach((b) =>
  b.addEventListener("click", () => robot("button", { name: b.dataset.button })));
document.querySelectorAll("[data-clap]").forEach((b) =>
  b.addEventListener("click", () => robot("clap", { n: Number(b.dataset.clap) })));
$("#btn-lift").addEventListener("click", () => robot("lift", { up: !S.lifted }));
$("#btn-estop").addEventListener("click", () => {
  if (S.phase !== "running") return core.toast(tr("The simulation is not running: start it on the Table screen."));
  robot("estop", { on: !S.estop });
});

/* driving by hand: the command again every 200 ms while held, a stop on release (the driver's watchdog: 0.5 s) */
const DRIVE = { fwd: [0.1, 0], back: [-0.1, 0], left: [0, 1.6], right: [0, -1.6], stop: [0, 0] };
let driving = null;
function driveStart(dir) {
  driveStop(false);
  const [linear, angular] = DRIVE[dir];
  const send = () => robot("drive", { linear, angular });
  send();
  if (dir !== "stop") driving = setInterval(send, 200);
}
function driveStop(send = true) {
  if (driving) { clearInterval(driving); driving = null; if (send) robot("drive", { linear: 0, angular: 0 }); }
}
document.querySelectorAll("#pad [data-drive]").forEach((b) => {
  b.addEventListener("pointerdown", (e) => { e.preventDefault(); driveStart(b.dataset.drive); });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(ev, () => driveStop());
});
const KEYS = { ArrowUp: "fwd", ArrowDown: "back", ArrowLeft: "left", ArrowRight: "right" };
window.addEventListener("keydown", (e) => {
  if (!KEYS[e.key] || e.repeat || S.tab !== "table" || S.phase !== "running" || S.behaviour !== "none") return;
  if (e.target.closest && e.target.closest("input, textarea, select")) return;
  e.preventDefault();
  driveStart(KEYS[e.key]);
});
window.addEventListener("keyup", (e) => { if (KEYS[e.key]) driveStop(); });
window.addEventListener("blur", () => driveStop());

window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
$("#rail-toggle").addEventListener("click", () => railOpen($("#rail").classList.contains("app-rail--closed"), true));
$("#rail-agent").addEventListener("click", () => core.connectDialog());
$("#rail-about").addEventListener("click", () => core.aboutDialog());
$("#rail-restart").addEventListener("click", () => core.restartServer());
$("#rail-stop").addEventListener("click", () => core.stopServer());
document.querySelectorAll("#theme-seg [data-theme-pick]").forEach((b) =>
  b.addEventListener("click", () => { core.applyTheme(b.dataset.themePick); markTheme(); }));
document.addEventListener("core:theme", markTheme);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", markTheme);
if (document.body.dataset.version) $("#rail-about-label").textContent = `${tr("About")} · v${document.body.dataset.version}`;
{
  let saved = null;
  try { saved = localStorage.getItem("atl-ide-rail"); } catch (_) { /* private window */ }
  railOpen(saved ? saved === "open" : window.matchMedia("(min-width: 52rem)").matches);
}
translateDom(document.body);
new MutationObserver((changes) => {
  for (const c of changes) {
    const el = c.target.nodeType === 1 ? c.target : c.target.parentElement;
    if (el && el.closest("#core-dialog, #core-toast, #edge-connections, #edge-chat")) translateDom(el);
  }
}).observe(document.body, { childList: true, subtree: true });
markTheme();
showTab(location.hash.slice(1));
