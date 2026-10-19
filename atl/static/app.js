// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Atelier-5
//
// app.js — the atl-ide page. core.js has already wired the header;
// window.core offers api(), dialog(), toast() and friends.

"use strict";

const $ = (sel) => document.querySelector(sel);
const WORKSPACE = true;

const S = {
  name: null,        // saved name, null while unsaved
  folder: null,      // where it came from
  version: null,     // the version it was read at, sent back on save
  dirty: false,
};

function readForm() {
  return {
    title: $("#f-title").value.trim(),
    body: $("#f-body").value,
    tags: $("#f-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
  };
}

function fillForm(note) {
  $("#f-title").value = note.title || "";
  $("#f-body").value = note.body || "";
  $("#f-tags").value = (note.tags || []).join(", ");
}

function status(text) { $("#status").textContent = text; }

async function summarise() {
  try {
    const out = await core.api("POST", "/api/summarise", { note: readForm() });
    $("#summary").hidden = false;
    $("#summary").textContent = JSON.stringify(out, null, 2);
  } catch (err) {
    core.toast(err.errors.join("; "), true);
  }
}

/* ---------------------------------------------------------- workspace -- */

async function refreshList() {
  const list = $("#note-list");
  let notes;
  try { notes = await core.api("GET", "/api/notes"); }
  catch (err) { list.innerHTML = `<p class="note">${core.esc(err.errors[0])}</p>`; return; }
  if (!notes.length) { list.innerHTML = '<p class="note">Nothing saved yet.</p>'; return; }
  list.innerHTML = notes.map((n) => `
    <button class="row${n.name === S.name && n.folder === S.folder ? " is-on" : ""}"
            data-name="${core.esc(n.name)}" data-folder="${core.esc(n.folder)}">
      <span>${core.esc(n.name)}</span><span class="tag">${core.esc(n.folder)}</span>
    </button>`).join("");
  list.querySelectorAll("button.row").forEach((b) =>
    b.addEventListener("click", () => openNote(b.dataset.name, b.dataset.folder)));
}

async function openNote(name, folder) {
  if (S.dirty && !confirm("Discard your unsaved changes?")) return;
  try {
    const got = await core.api("GET", `/api/notes/${encodeURIComponent(name)}?folder=${encodeURIComponent(folder)}`);
    Object.assign(S, { name: got.name, folder: got.folder, version: got.version, dirty: false });
    $("#f-name").value = got.name;
    fillForm(got.data);
    status(`${got.folder} · ${got.version}`);
    refreshList();
  } catch (err) { core.toast(err.errors.join("; "), true); }
}

async function saveNote(force = false) {
  const name = $("#f-name").value.trim();
  if (!name) { core.toast("Give it a name first.", true); return; }
  const sameDoc = name === S.name;
  try {
    const saved = await core.api("PUT", `/api/notes/${encodeURIComponent(name)}`, {
      note: readForm(),
      folder: sameDoc ? S.folder : null,
      base_version: sameDoc && !force ? S.version : null,
    });
    Object.assign(S, { name: saved.name, folder: saved.folder, version: saved.version, dirty: false });
    status(`saved to ${saved.folder} · ${saved.version}`);
    refreshList();
  } catch (err) {
    if (err.status === 409) {
      core.dialog("Changed elsewhere", `
        <p class="note">Someone else (another tab, or an agent) saved “${core.esc(name)}”
          after you opened it.</p>
        <div class="actions">
          <button value="cancel">Cancel</button>
          <button type="button" id="q-theirs">Load theirs</button>
          <button type="button" class="danger" id="q-mine">Keep mine</button>
        </div>`, (form, dlg) => {
        form.querySelector("#q-theirs").addEventListener("click", () => {
          dlg.close(); S.dirty = false; openNote(name, S.folder);
        });
        form.querySelector("#q-mine").addEventListener("click", () => { dlg.close(); saveNote(true); });
      });
      return;
    }
    core.toast(err.errors.join("; "), true);
  }
}

async function deleteNote() {
  if (!S.name || !confirm(`Delete “${S.name}” from ${S.folder}?`)) return;
  try {
    await core.api("DELETE", `/api/notes/${encodeURIComponent(S.name)}?folder=${encodeURIComponent(S.folder)}`);
    newNote(true);
    refreshList();
  } catch (err) { core.toast(err.errors.join("; "), true); }
}

function newNote(skipCheck = false) {
  if (!skipCheck && S.dirty && !confirm("Discard your unsaved changes?")) return;
  Object.assign(S, { name: null, folder: null, version: null, dirty: false });
  $("#f-name").value = "";
  fillForm({});
  status("");
}

/* --------------------------------------------------------------- wire -- */

document.querySelectorAll("#f-title, #f-body, #f-tags").forEach((el) =>
  el.addEventListener("input", () => { S.dirty = true; }));
$("#btn-summarise").addEventListener("click", summarise);

if (WORKSPACE) {
  $("#btn-new").addEventListener("click", () => newNote());
  $("#btn-save").addEventListener("click", () => saveNote());
  $("#btn-delete").addEventListener("click", deleteNote);
  refreshList();

  // Stop and Restart take the server away; unsaved work lives only in this tab.
  core.setLeavingGuard((verb, go) => core.defaultLeaving(verb, go, S.dirty
    ? `<b>“${core.esc(S.name || "untitled")}” has unsaved changes</b>, which live only in this tab. Save first to keep them.`
    : ""));
  window.addEventListener("beforeunload", (ev) => { if (S.dirty) { ev.preventDefault(); ev.returnValue = ""; } });
}
