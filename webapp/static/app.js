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
  state[which] = b;
  renderSlot(which);
  // Helpfully prefill title/author/language from the original.
  if (which === "src") {
    if (!$("title").value) $("title").value = b.title;
    if (!$("author").value) $("author").value = b.authors;
    const lang = (b.languages[0] || "").toLowerCase();
    if ([...$("srcLang").options].some((o) => o.value === lang)) $("srcLang").value = lang;
  }
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
  body.querySelector(".clear").onclick = () => { state[which] = null; renderSlot(which); };
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
$("prev").onclick = () => showPage(state.page - 1);
$("next").onclick = () => showPage(state.page + 1);
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "ArrowLeft") showPage(state.page - 1);
  if (e.key === "ArrowRight") showPage(state.page + 1);
});
