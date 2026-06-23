"use strict";

const $ = (id) => document.getElementById(id);

// Selected editions and current preview state.
const state = {
  src: null,        // {id, title, authors, languages}
  tgt: null,
  job: null,
  page: 0,
  pages: 0,
  poll: null,
};

// --------------------------------------------------------------------------- //
// Fonts (populated from installed fonts on load)
// --------------------------------------------------------------------------- //
const CATEGORY_LABELS = {
  serif: "Classic serif", medieval: "Medieval / display",
  greek: "Greek display", other: "Other",
};
let FONTS = [];

async function loadFonts() {
  try {
    const data = await (await fetch("/api/fonts")).json();
    FONTS = data.fonts || [];
  } catch { FONTS = []; }
  const sel = $("font");
  sel.innerHTML = "";
  if (!FONTS.length) {
    sel.innerHTML = `<option value="Cardo">Cardo (none installed — run download_fonts.py)</option>`;
    return;
  }
  const byCat = {};
  for (const f of FONTS) (byCat[f.category] ||= []).push(f);
  for (const cat of ["serif", "medieval", "greek", "other"]) {
    if (!byCat[cat]) continue;
    const group = document.createElement("optgroup");
    group.label = CATEGORY_LABELS[cat] || cat;
    for (const f of byCat[cat]) {
      const o = document.createElement("option");
      o.value = f.id;
      o.textContent = f.label + (f.greek ? "  ·  ✔ Greek" : "");
      group.appendChild(o);
    }
    sel.appendChild(group);
  }
  if (FONTS.some((f) => f.id === "cardo")) sel.value = "cardo";
  updateFontNote();
}

function updateFontNote() {
  const f = FONTS.find((x) => x.id === $("font").value);
  const note = $("fontNote");
  if (!f) { note.textContent = ""; return; }
  const isGreek = $("srcLang").value === "el" || $("srcLang").value === "grc";
  if (isGreek && f.greek === false)
    note.textContent = "⚠ This font lacks Greek glyphs — pick a ✔ Greek font.";
  else
    note.textContent = "";
}

// --------------------------------------------------------------------------- //
// Search
// --------------------------------------------------------------------------- //
async function doSearch() {
  const q = $("q").value.trim();
  if (!q) return;
  const lang = $("lang").value;
  const box = $("results");
  box.innerHTML = `<div class="result muted">Searching…</div>`;
  try {
    const url = `/api/search?q=${encodeURIComponent(q)}&lang=${encodeURIComponent(lang)}`;
    const data = await (await fetch(url)).json();
    if (data.error) { box.innerHTML = `<div class="result">⚠ ${data.error}</div>`; return; }
    if (!data.results.length) { box.innerHTML = `<div class="result muted">No results.</div>`; return; }
    box.innerHTML = "";
    for (const b of data.results) box.appendChild(resultRow(b));
  } catch (e) {
    box.innerHTML = `<div class="result">⚠ ${e}</div>`;
  }
}

function resultRow(b) {
  const row = document.createElement("div");
  row.className = "result";
  const langs = b.languages.join(", ");
  const txt = b.has_text ? "" : `<span class="badge">no plain text</span>`;
  row.innerHTML = `
    <div class="meta">
      <b>${escapeHtml(b.title)}</b>
      <small>${escapeHtml(b.authors)} · #${b.id} · ${langs} ${txt}</small>
    </div>
    <div class="pick">
      <button data-role="src">→ Original</button>
      <button data-role="tgt">→ Translation</button>
    </div>`;
  row.querySelector('[data-role="src"]').onclick = () => selectEdition("src", b);
  row.querySelector('[data-role="tgt"]').onclick = () => selectEdition("tgt", b);
  return row;
}

// --------------------------------------------------------------------------- //
// Selection
// --------------------------------------------------------------------------- //
function selectEdition(which, b) {
  state[which] = { ...b };
  renderSlot(which);
  loadOutline(which);
  // Helpfully prefill title/author/language from the original.
  if (which === "src") {
    if (!$("title").value) $("title").value = b.title;
    if (!$("author").value) $("author").value = b.authors;
    const lang = (b.languages[0] || "").toLowerCase();
    if ([...$("srcLang").options].some((o) => o.value === lang)) $("srcLang").value = lang;
  }
}

// --- Division outline + range picker (so both sides match in scope) --- //
async function loadOutline(which) {
  const b = state[which];
  const box = $(which === "src" ? "range-src" : "range-tgt");
  if (!b || !b.id) { box.innerHTML = ""; return; }
  box.innerHTML = `<small class="muted">loading outline…</small>`;
  try {
    const data = await (await fetch(`/api/outline?id=${b.id}`)).json();
    b.outline = data.divisions || [];
  } catch { box.innerHTML = `<small class="muted">outline unavailable</small>`; return; }
  renderRange(which);
}

function renderRange(which) {
  const b = state[which];
  const box = $(which === "src" ? "range-src" : "range-tgt");
  const divs = b && b.outline;
  if (!divs || divs.length <= 1) { box.innerHTML = ""; return; }
  const opts = divs.map((d) => {
    const t = d.title.length > 30 ? d.title.slice(0, 29) + "…" : d.title;
    return `<option value="${d.index}">${d.index}. ${escapeHtml(t)}</option>`;
  }).join("");
  box.innerHTML = `<div class="rng">
      <span>from</span><select data-end="from">${opts}</select>
      <span>to</span><select data-end="to">${opts}</select></div>`;
  // Default: skip front matter (division 1), span the remaining divisions.
  box.querySelector('[data-end="from"]').value = divs.length > 1 ? "2" : "1";
  box.querySelector('[data-end="to"]').value = String(divs[divs.length - 1].index);
}

function getRange(which) {
  const box = $(which === "src" ? "range-src" : "range-tgt");
  const from = box.querySelector('[data-end="from"]');
  const to = box.querySelector('[data-end="to"]');
  return from && to ? [parseInt(from.value, 10), parseInt(to.value, 10)] : null;
}

function renderSlot(which) {
  const slot = $(which === "src" ? "slot-src" : "slot-tgt");
  const body = slot.querySelector(".slot-body");
  const b = state[which];
  if (!b) {
    slot.classList.remove("filled");
    body.className = "slot-body muted";
    body.textContent = "none selected";
    return;
  }
  slot.classList.add("filled");
  body.className = "slot-body";
  body.innerHTML = `<b>${escapeHtml(b.title)}</b>
    <small class="muted">${escapeHtml(b.authors)} · #${b.id}</small>
    <span class="clear">clear</span>`;
  body.querySelector(".clear").onclick = () => {
    state[which] = null;
    renderSlot(which);
    $(which === "src" ? "range-src" : "range-tgt").innerHTML = "";
  };
}

// --------------------------------------------------------------------------- //
// Build
// --------------------------------------------------------------------------- //
async function doBuild() {
  if (!state.src) return alert("Pick an Original edition.");
  if (!state.tgt) return alert("Pick a Translation edition.");
  if (!$("pd").checked)
    return alert("Confirm the translation is public domain before building.");

  const payload = {
    src_id: state.src.id,
    tgt_id: state.tgt.id,
    title: $("title").value || state.src.title,
    author: $("author").value || "Unknown",
    src_lang: $("srcLang").value,
    mode: $("mode").value,
    aligner: $("aligner").value,
    first: $("first").value,
    font: $("font").value,
    trim: [parseFloat($("trimW").value), parseFloat($("trimH").value)],
    translation_pd_confirmed: true,
    src_range: getRange("src"),
    tgt_range: getRange("tgt"),
    decorations: { margin: $("margin").value, chapter: $("chapter").value },
  };

  $("buildBtn").disabled = true;
  $("log").textContent = "Queued…\n";
  resetPreview();
  try {
    const res = await fetch("/api/build", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    state.job = data.job_id;
    pollStatus();
  } catch (e) {
    $("log").textContent += `\n⚠ ${e}`;
    $("buildBtn").disabled = false;
  }
}

function pollStatus() {
  if (state.poll) clearInterval(state.poll);
  state.poll = setInterval(async () => {
    const data = await (await fetch(`/api/status/${state.job}`)).json();
    $("log").textContent = data.log.join("\n");
    $("log").scrollTop = $("log").scrollHeight;
    if (data.status === "done") {
      clearInterval(state.poll);
      $("buildBtn").disabled = false;
      state.pages = data.pages;
      state.page = 0;
      $("download").href = `/api/download/${state.job}.pdf`;
      $("download").style.display = "inline-block";
      showPage(0);
    } else if (data.status === "error") {
      clearInterval(state.poll);
      $("buildBtn").disabled = false;
    }
  }, 700);
}

// --------------------------------------------------------------------------- //
// Preview
// --------------------------------------------------------------------------- //
function resetPreview() {
  state.pages = 0;
  $("previewWrap").innerHTML = `<p class="muted">Building…</p>`;
  $("pageLabel").textContent = "— / —";
  $("download").style.display = "none";
}

function showPage(i) {
  if (!state.job || state.pages === 0) return;
  state.page = Math.max(0, Math.min(i, state.pages - 1));
  const url = `/api/preview/${state.job}/${state.page}.png?t=${Date.now()}`;
  $("previewWrap").innerHTML = `<img alt="page ${state.page + 1}" src="${url}">`;
  $("pageLabel").textContent = `${state.page + 1} / ${state.pages}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// --------------------------------------------------------------------------- //
// Wire up
// --------------------------------------------------------------------------- //
$("searchBtn").onclick = doSearch;
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
$("buildBtn").onclick = doBuild;
$("font").addEventListener("change", updateFontNote);
$("srcLang").addEventListener("change", updateFontNote);
loadFonts();
$("prev").onclick = () => showPage(state.page - 1);
$("next").onclick = () => showPage(state.page + 1);
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "ArrowLeft") showPage(state.page - 1);
  if (e.key === "ArrowRight") showPage(state.page + 1);
});
