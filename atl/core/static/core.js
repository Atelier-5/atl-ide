/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 D-LAB-5
 *
 * core.js — the behaviour every D-LAB-5 tool page shares.
 *
 * Loaded by core/_base.html before the tool's own app.js, it wires the header
 * (theme, About, Restart, Stop) and exposes a few helpers as window.core:
 *
 *   core.api(method, path, payload)   fetch JSON; throws {status, data, errors}
 *   core.dialog(title, html, onOpen)  one modal <dialog>, reused
 *   core.esc(text)                    HTML-escape
 *   core.toast(message, bad)
 *   core.aboutDialog() / core.stopServer() / core.restartServer()
 *   core.setLeavingGuard(fn)          fn(verb, go): a tool with unsaved work
 *                                     decides whether and how to go
 *   core.defaultLeaving(verb, go, html)  the standard confirmation, for a guard
 *                                     to fall back on or add a warning to
 *
 * Core-owned. Put tool behaviour in static/app.js.
 */

(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const body = () => document.body.dataset;
  const title = () => body().title || document.title;

  /* ------------------------------------------------------------ fetch -- */

  async function api(method, path, payload) {
    const opts = { method, headers: {} };
    if (payload !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(payload);
    }
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      throw { status: res.status, data,
              errors: (data && data.errors) || [`${method} ${path} failed (${res.status})`] };
    }
    return data;
  }

  /* ----------------------------------------------------------- dialog -- */

  function dialog(heading, bodyHTML, onOpen) {
    let dlg = $("#core-dialog");
    if (!dlg) {
      dlg = document.createElement("dialog");
      dlg.id = "core-dialog";
      dlg.className = "core-dialog";
      dlg.innerHTML = '<form method="dialog" id="core-dialog-form"></form>';
      document.body.appendChild(dlg);
    }
    const form = $("#core-dialog-form");
    form.innerHTML = `<h2>${esc(heading)}</h2>${bodyHTML}`;
    if (dlg.open) dlg.close();
    dlg.showModal();
    if (onOpen) onOpen(form, dlg);
    return dlg;
  }

  let toastTimer;
  function toast(message, bad = false) {
    let el = $("#core-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "core-toast";
      el.className = "core-toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.toggle("bad", !!bad);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, bad ? 7000 : 3500);
  }

  /* ------------------------------------------------------------ theme -- */

  // A per-browser preference, so localStorage is its home, and storage may be
  // unavailable (private mode, blocked site data): never let that break the page.
  const themeKey = () => `${body().tool || "tool"}:theme`;

  function applyTheme(theme) {
    const value = ["auto", "light", "dark"].includes(theme) ? theme : "auto";
    const root = document.documentElement;
    if (value === "auto") delete root.dataset.theme;
    else root.dataset.theme = value;
    try { localStorage.setItem(themeKey(), value); } catch (_) { /* no storage */ }
    const select = $("#core-theme");
    if (select && select.value !== value) select.value = value;
    document.dispatchEvent(new CustomEvent("core:theme", { detail: value }));
    return value;
  }

  function savedTheme() {
    try { return localStorage.getItem(themeKey()) || "auto"; } catch (_) { return "auto"; }
  }

  /* ------------------------------------------------- stop and restart -- */

  let leavingGuard = null;
  let beforeGone = [];

  /** fn(verb, go): call go() when it is safe to take the server away. */
  function setLeavingGuard(fn) { leavingGuard = fn; }
  /** fn(): run just before the page is replaced: clear timers, drop listeners. */
  function onGone(fn) { beforeGone.push(fn); }

  function confirmLeaving(verb, go) {
    if (leavingGuard) { leavingGuard(verb, go); return; }
    defaultLeaving(verb, go);
  }

  /** The standard "Stop/Restart the tool?" dialog. A guard with nothing to
      protect calls this; one with something at stake passes extraHTML to say what. */
  function defaultLeaving(verb, go, extraHTML = "") {
    const Verb = verb[0].toUpperCase() + verb.slice(1);
    dialog(`${Verb} ${title()}?`, `
      <p class="core-note">${verb === "restart"
        ? "The server starts again on the same port and the page reloads."
        : "This shuts down the local server."} Anything already written to
        disk stays where it is.</p>
      ${extraHTML ? `<p class="core-note">${extraHTML}</p>` : ""}
      <div class="actions">
        <button value="cancel">Cancel</button>
        <button type="button" class="${verb === "restart" ? "primary" : "danger"}" id="core-go">${Verb}</button>
      </div>`, (form, dlg) =>
      form.querySelector("#core-go").addEventListener("click", () => { dlg.close(); go(); }));
  }

  function gone() {
    beforeGone.forEach((fn) => { try { fn(); } catch (_) { /* leaving anyway */ } });
    beforeGone = [];
  }

  function startHint() {
    const cmd = esc(body().webCommand || "the tool");
    return `Run <code>./run.sh</code> in the checkout (or <code>run.cmd</code> /
      <code>run.ps1</code> on Windows), or <code>${cmd}</code> if it is installed.`;
  }

  function shutDown() {
    gone();
    // the server answers, then exits: a failed fetch here is the expected ending
    fetch("/api/shutdown", { method: "POST" })
      .catch(() => {})
      .finally(() => {
        document.body.innerHTML =
          `<div class="stopped"><h1>${esc(title())} stopped</h1>
           <p>The local server has shut down. ${startHint()}</p></div>`;
      });
  }

  /** Ask the server to replace itself, then reload once it answers again. */
  async function restartNow() {
    gone();
    document.body.innerHTML =
      `<div class="stopped"><h1>Restarting…</h1>
       <p id="core-restart-note">Waiting for ${esc(title())} to come back.</p></div>`;
    fetch("/api/restart", { method: "POST" }).catch(() => {});  // it may die mid-answer

    // It has to go away and come back. execv keeps the pid, so "the pid
    // changed" cannot be the signal; wait past the moment it replaces itself.
    await new Promise((r) => setTimeout(r, 900));
    for (let tries = 0; tries < 40; tries += 1) {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (res.ok) { location.reload(); return; }
      } catch (_) { /* still down */ }
      await new Promise((r) => setTimeout(r, 400));
    }
    const note = document.getElementById("core-restart-note");
    if (note) note.innerHTML = `It did not come back. ${startHint()}`;
  }

  function stopServer() { confirmLeaving("stop", shutDown); }
  function restartServer() { confirmLeaving("restart", restartNow); }

  /* ------------------------------------------------------------ about -- */

  /** Version, licence, where this came from, and how to move it forward. */
  async function aboutDialog() {
    dialog(`About ${title()}`, `
      <div class="about">
        <img class="about-logo" src="/core-static/dlab5.png" alt="D-LAB-5" width="88" height="88">
        <p class="about-lead" id="core-a-lead"></p>
        <dl class="about-grid" id="core-a-grid">
          <dt>Installed</dt><dd id="core-a-installed">…</dd>
          <dt>Latest</dt><dd id="core-a-latest">checking…</dd>
        </dl>
        <p class="core-note" id="core-a-note"></p>
        <h3 class="about-h">Services</h3>
        <ul class="svc" id="core-a-svc"><li class="svc-wait">checking…</li></ul>
        <p class="about-disclaimer" id="core-a-disclaimer" hidden></p>
        <pre class="about-log" id="core-a-log" hidden></pre>
        <p class="about-foot" id="core-a-foot"></p>
      </div>
      <div class="actions">
        <button type="button" id="core-a-update" class="warn-btn" hidden>Update and restart</button>
        <button value="cancel" class="primary">Close</button>
      </div>`);

    // asked alongside the version, not after it: a tool's own checks may take
    // a few seconds to reach their backends, and the rest of the box need not wait
    showServices();

    let info;
    try { info = await api("GET", "/api/version"); } catch (_) { info = null; }
    const installed = $("#core-a-installed");
    if (!installed) return;                       // dialog closed while we asked
    const latest = $("#core-a-latest");
    const note = $("#core-a-note");

    if (!info) {
      installed.textContent = "unknown";
      latest.textContent = "—";
      note.textContent = "The server did not answer.";
      return;
    }

    $("#core-a-lead").textContent = info.description || "";
    const grid = $("#core-a-grid");
    const row = (dt, ddHTML) => grid.insertAdjacentHTML("beforeend", `<dt>${esc(dt)}</dt><dd>${ddHTML}</dd>`);
    const link = (href, text) =>
      `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`;
    row("Repository", link(info.repo, info.repo.replace("https://", "")));
    if (info.template) {
      const t = info.template;
      const said = `${t.name} ${t.version}` + (t.released ? "" : " (unreleased)");
      row("Built on", t.url ? link(t.url, said) : esc(said));
    }
    row("Licence", link(info.licence_url, info.licence));
    Object.entries(info.extras || {}).forEach(([k, v]) => row(k, esc(v)));
    if (info.disclaimer) {
      const d = $("#core-a-disclaimer");
      d.textContent = info.disclaimer;
      d.hidden = false;
    }
    $("#core-a-foot").innerHTML = `${esc(info.copyright)} — Twin. Experiment. Automate.`
      + (info.coffee ? `<br>${link(info.coffee, "☕ Buy me a coffee")}` : "");

    installed.textContent = info.installed;
    if (info.disabled) {
      latest.textContent = "not checked";
      note.textContent = "The update check is off (--no-update-check).";
    } else if (info.offline || !info.latest) {
      latest.textContent = "unknown";
      note.textContent = "Could not reach github.com — offline, or behind a proxy.";
    } else if (info.update_available) {
      latest.innerHTML = `<strong>${esc(info.latest)}</strong> — ${link(info.releases, "release notes")}`;
      // pip can only upgrade what pip installed; a checkout is git's business
      if (info.install === "installed") {
        note.textContent = `You are on ${info.installed}. Updating runs pip, then restarts.`;
        const btn = $("#core-a-update");
        btn.hidden = false;
        btn.addEventListener("click", () => runUpdate(btn));
      } else {
        note.textContent = `You are on ${info.installed}, running from a checkout — `
          + "update it with git pull, then press Restart.";
      }
    } else {
      latest.textContent = info.latest;
      note.textContent = "Up to date.";
    }
  }

  /** Each part of the tool with a dot: green up, red down, grey not part of it. */
  async function showServices() {
    let rows;
    try { rows = (await api("GET", "/api/services")).services || []; }
    catch (_) { rows = null; }
    const list = $("#core-a-svc");
    if (!list) return;                            // dialog closed while we asked
    if (!rows) {
      list.innerHTML = `<li class="svc-wait">The server did not say.</li>`;
      return;
    }
    const word = { up: "up", down: "down", off: "not enabled" };
    list.innerHTML = rows.map((s) => `
      <li class="svc-row is-${esc(s.state)}">
        <span class="svc-dot" role="img" aria-label="${esc(word[s.state] || s.state)}"
              title="${esc(word[s.state] || s.state)}"></span>
        <span class="svc-name">${esc(s.name)}</span>
        <span class="svc-detail">${esc(s.detail)}</span>
      </li>`).join("");
  }

  /** Ask the server to pip-upgrade itself, then restart into it if that worked. */
  async function runUpdate(btn) {
    const note = $("#core-a-note");
    const log = $("#core-a-log");
    btn.disabled = true;
    btn.textContent = "Updating…";
    note.textContent = "Running pip. This can take a minute.";
    let out;
    try { out = await api("POST", "/api/update"); }
    catch (err) {
      out = (err.data && err.data.output) ? err.data : { ok: false, output: (err.errors || []).join("\n") };
    }
    if (log) { log.hidden = false; log.textContent = out.output || ""; }
    if (!out.ok) {
      btn.disabled = false;
      btn.textContent = "Try again";
      note.textContent = "The update did not go through — nothing has changed.";
      return;
    }
    // the files are new; only a restart runs them
    note.textContent = "Updated. Restarting to run the new version.";
    btn.textContent = "Restarting…";
    restartNow();
  }

  /* ----------------------------------------------------------- connect -- */

  /** Point an agent at this tool: the config to paste, and who is connected.
   *
   * There is deliberately no start button. An MCP server is spawned by its
   * client, lives on that client's stdio pipes and dies with it, so a web page
   * has nothing to start and nothing to kill. What it can do is hand over the
   * configuration and report traffic it has actually seen.
   */
  async function connectDialog() {
    dialog(`Connect an agent to ${title()}`, `
      <div class="agent">
        <p class="agent-status" id="core-g-status">
          <span class="agent-dot"></span><span id="core-g-status-text">checking…</span>
        </p>
        <div class="agent-pick">
          <label for="core-g-target">Agent</label>
          <select id="core-g-target"></select>
        </div>
        <p class="agent-where" id="core-g-where"></p>
        <pre class="agent-config" id="core-g-config">…</pre>
        <p class="core-note" id="core-g-note"></p>
        <p class="agent-cannot" id="core-g-cannot" hidden></p>
      </div>
      <div class="actions">
        <button type="button" id="core-g-copy">Copy</button>
        <button type="button" id="core-g-write" class="warn-btn" hidden>Write the file</button>
        <button value="cancel" class="primary">Close</button>
      </div>`);

    let info;
    try { info = await api("GET", "/api/agent"); } catch (_) { info = null; }
    const select = $("#core-g-target");
    if (!select) return;                          // closed while we asked

    if (!info || info.available === false) {
      $("#core-g-config").hidden = true;
      $("#core-g-copy").hidden = true;
      $("#core-g-where").textContent = "";
      $("#core-g-note").textContent =
        (info && info.why) || "The server did not answer.";
      select.closest(".agent-pick").hidden = true;
      return;
    }

    showAgentStatus(info.status);
    info.targets.forEach((t, i) => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.name;
      if (i === 0) opt.selected = true;
      select.appendChild(opt);
    });

    const show = () => {
      const t = info.targets.find((x) => x.id === select.value);
      if (!t) return;
      $("#core-g-config").textContent = t.config;
      $("#core-g-where").textContent = t.path ? t.path : "";
      const bits = [];
      if (t.note) bits.push(t.note);
      if (t.instructions) {
        bits.push(`The ${t.instructions.what} goes in ${t.instructions.path} — `
          + `${t.instructions.how}`);
      }
      $("#core-g-note").textContent = bits.join(" ");
      $("#core-g-write").hidden = !t.path;
    };
    select.addEventListener("change", show);
    show();

    $("#core-g-cannot").hidden = false;
    $("#core-g-cannot").textContent =
      "An agent starts its own copy of the MCP server, so there is nothing to "
      + "start or stop from here. Paste the configuration into your agent and "
      + "it connects on its next start.";

    $("#core-g-copy").addEventListener("click", async () => {
      const text = $("#core-g-config").textContent;
      try {
        await navigator.clipboard.writeText(text);
        toast("Configuration copied.");
      } catch (_) {
        // clipboard needs a secure context and permission; selecting it is
        // always allowed, and leaves the person one keystroke from copying
        const pre = $("#core-g-config");
        const range = document.createRange();
        range.selectNodeContents(pre);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        toast("Selected — press Ctrl+C to copy.", true);
      }
    });

    $("#core-g-write").addEventListener("click", async (ev) => {
      const t = info.targets.find((x) => x.id === select.value);
      if (!t || !t.path) return;
      const btn = ev.currentTarget;
      btn.disabled = true;
      try {
        const out = await api("POST", "/api/agent/write", { target: t.id });
        toast(`Written to ${out.written_to}`);
      } catch (err) {
        toast((err.errors || ["could not write it"])[0], true);
      } finally {
        btn.disabled = false;
      }
    });
  }

  function showAgentStatus(status) {
    const box = $("#core-g-status");
    const text = $("#core-g-status-text");
    if (!box || !text || !status) return;
    box.classList.toggle("live", !!status.connected);
    if (status.connected) {
      const ago = status.seconds_ago;
      const when = ago < 5 ? "just now"
        : ago < 90 ? `${ago}s ago`
        : `${Math.round(ago / 60)} min ago`;
      text.textContent = `${status.client} last called ${when}.`;
    } else {
      text.textContent = "No agent has called this server yet.";
    }
  }

  /** The header dot: a quiet sign that an agent is working here too. */
  async function pollAgent() {
    const dot = document.getElementById("core-agent-dot");
    if (!dot) return;                             // tool built without MCP
    try {
      const info = await api("GET", "/api/agent");
      dot.hidden = !(info && info.status && info.status.connected);
    } catch (_) { dot.hidden = true; }
  }

  /* ------------------------------------------------------------- wire -- */

  function wire() {
    applyTheme(savedTheme());
    const select = $("#core-theme");
    if (select) select.addEventListener("change", () => applyTheme(select.value));
    const on = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener("click", fn); };
    on("core-about", aboutDialog);
    on("core-connect", connectDialog);
    on("core-stop", stopServer);
    on("core-restart", restartServer);
    // a tool without MCP has no dot and pollAgent returns at once
    pollAgent();
    setInterval(pollAgent, 30000);
  }

  window.core = {
    api, dialog, esc, toast, applyTheme,
    aboutDialog, connectDialog, runUpdate, stopServer, restartServer,
    setLeavingGuard, defaultLeaving, onGone,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();
})();
