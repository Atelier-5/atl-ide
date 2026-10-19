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

// Until the simulation routes exist (step 6), the Table screen's controls say so instead of failing.
const notYet = () => core.toast(tr("The simulation comes in the next steps of v0.1."));
["#btn-start", "#btn-estop"].forEach((s) => $(s).addEventListener("click", notYet));

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
