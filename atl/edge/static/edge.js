// SPDX-License-Identifier: GPL-3.0-or-later
// The edge layer's panels, for any tool's page: put
//   <section id="edge-connections"></section>
//   <section id="edge-chat"></section>          (optional)
//   <script src="/edge-static/edge.js" defer></script>
// in templates/index.html (scripts/edge-wire.py does it). Owned by the edge
// layer; plain DOM, no framework, text never inserted as HTML.
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : String(k));
    return e;
  };
  async function api(method, path, body) {
    const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {},
                                  body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error((data.errors && data.errors[0]) || data.description || `${r.status}`);
    return data;
  }
  const host = (u) => { try { return new URL(u).host; } catch { return u || ""; } };

  // ------------------------------------------------------------ connections --
  const box = $("#edge-connections");
  let poll = null;
  async function connections() {
    if (!box) return;
    let st;
    try { st = await api("GET", "/api/cloud"); } catch (e) { box.replaceChildren(el("p", { class: "err" }, e.message)); return; }
    const rows = Object.entries(st.profiles || {}).map(([name, c]) => el("li", { class: `edge-conn${name === st.profile ? " is-current" : ""}` },
      el("span", { class: `edge-dot ${c.linked ? "ok" : "off"}`, title: c.linked ? "linked" : "not linked" }, "●"), " ",
      el("b", {}, host(c.site) || name), " ",
      el("span", { class: "edge-tag" }, name + (name === st.profile ? " · current" : "")),
      c.tenant ? el("span", { class: "edge-tag" }, `${c.tenant.name} · ${c.spaces.length} space${c.spaces.length === 1 ? "" : "s"}`) : null,
      c.no_tenant ? el("span", { class: "edge-tag err" }, "no tenant: link again") : null,
      c.rotate_error ? el("span", { class: "edge-tag err", title: c.rotate_error }, "token renewal failed") : null,
      c.token_expires ? el("span", { class: "edge-tag" }, `token until ${c.token_expires.slice(0, 10)}`) : null,
      name !== st.profile ? el("button", { type: "button", on: { click: () => api("POST", "/api/cloud/use", { profile: name }).then(connections) } }, "use") : null,
      el("button", { type: "button", on: { click: () => { if (confirm(`Forget ${name} on this edge?`)) api("POST", "/api/cloud/unlink", { profile: name }).then(connections); } } }, "unlink")));
    const link = st.link || {};
    const form = el("form", { class: "edge-link", on: { submit: (ev) => {
      ev.preventDefault();
      const f = ev.target;
      api("POST", "/api/cloud/link", { cloud: f.cloud.value.trim(), profile: f.profile.value.trim() || null })
        .then(connections).catch((e) => alert(e.message));
    } } },
      el("input", { name: "cloud", placeholder: "edge API address (the cloud's About page)", required: true, size: 48 }),
      el("input", { name: "profile", placeholder: "name, e.g. prod", pattern: "[a-z][a-z0-9-]{0,31}", size: 10 }),
      el("button", { type: "submit" }, "+ Add connection"));
    const pairing = link.state === "waiting" ? el("p", { class: "edge-pairing" },
      "Ask an admin of your tenant to approve code ", el("b", {}, link.user_code || "…"), " on ",
      el("a", { href: link.url, target: "_blank", rel: "noopener noreferrer" }, host(link.url)), ".")
      : link.state === "failed" ? el("p", { class: "err" }, link.error) : null;
    box.replaceChildren(el("h2", {}, "Connections"), el("ul", { class: "edge-conns" }, rows.length ? rows : el("li", {}, "Not linked to a cloud yet.")), pairing, form);
    clearTimeout(poll);
    if (link.state === "waiting") poll = setTimeout(connections, 3000);
  }

  // ------------------------------------------------------------------- chat --
  const chatBox = $("#edge-chat");
  async function chatPanel() {
    if (!chatBox) return;
    const st = await api("GET", "/api/chat").catch(() => ({ available: false, why: "no answer" }));
    if (!st.available) { chatBox.replaceChildren(el("h2", {}, "Chat"), el("p", { class: "edge-muted" }, st.why)); return; }
    const log = el("div", { class: "edge-chat__log", "aria-live": "polite" });
    const input = el("textarea", { rows: 2, placeholder: "Ask about this edge…" });
    const decide = (id, what, row) => api("POST", `/api/chat/proposals/${id}/${what}`)
      .then((r) => row.replaceChildren(what === "confirm" ? `✓ done (${r.status})` : "dismissed"))
      .catch((e) => row.replaceChildren(e.message));
    async function send() {
      const message = input.value.trim();
      if (!message) return;
      input.value = "";
      log.append(el("p", { class: "edge-chat__me" }, message));
      const answer = el("p", { class: "edge-chat__them" });
      log.append(answer);
      const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, lang: (document.documentElement.lang || "en").slice(0, 2) }) });
      if (!r.ok || !r.body) { answer.textContent = `error ${r.status}`; return; }
      const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
          let ev; try { ev = JSON.parse(line); } catch { continue; }
          if (ev.t === "text") answer.append(ev.text);
          else if (ev.t === "proposal") {
            const row = el("p", { class: "edge-chat__proposal" }, ev.summary || ev.id, " ",
              el("button", { type: "button", on: { click: () => decide(ev.id, "confirm", row) } }, "Confirm"), " ",
              el("button", { type: "button", on: { click: () => decide(ev.id, "dismiss", row) } }, "Dismiss"));
            log.append(row);
          } else if (ev.t === "done" && ev.error) log.append(el("p", { class: "err" }, ev.error));
        }
      }
      connections();
    }
    chatBox.replaceChildren(el("h2", {}, "Chat"), log,
      el("form", { class: "edge-chat__ask", on: { submit: (ev) => { ev.preventDefault(); send(); } } }, input,
        el("button", { type: "submit" }, "Ask"),
        el("button", { type: "button", on: { click: () => api("POST", "/api/chat/new").then(() => log.replaceChildren()) } }, "New")));
  }

  connections();
  chatPanel();
  setInterval(connections, 60000);
})();
