"use strict";

const $ = (id) => document.getElementById(id);

// Selected editions, corpus pick, and current preview state.
const state = {
  source: "gutenberg",   // "gutenberg" | "corpus" | "local"
  src: null,             // {id, title, authors, languages}
  tgt: null,
  corpus: null,          // {doc, sections, sample, note}
  lsrc: null,            // local file {name, path, kind, size_mb, outline}
  ltgt: null,
  job: null,
  page: 0,
  pages: 0,
  poll: null,
  viewingCover: false,
};

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function getJSON(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

function postJSON(url, body) {
  return getJSON(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --------------------------------------------------------------------------- //
// Tabs — which kind of source the build is drawn from
// --------------------------------------------------------------------------- //
function selectTab(name) {
  state.source = name;
  for (const t of document.querySelectorAll(".tab"))
    t.classList.toggle("active", t.dataset.tab === name);
  for (const p of document.querySelectorAll(".tabpane"))
    p.classList.toggle("active", p.id === `pane-${name}`);
  // The corpus is already sentence-aligned, so the aligner picker is moot there.
  for (const el of document.querySelectorAll(".gutenberg-only"))
    el.style.display = name === "corpus" ? "none" : "";
  updateSides();
}

// --------------------------------------------------------------------------- //
// Edition — dual-language, or one language on its own
// --------------------------------------------------------------------------- //
const SIDES_NOTE = {
  both: "",
  src: "Prints and narrates the original alone. Nothing of the translation " +
       "is published, so a translation's copyright stops mattering.",
  tgt: "Prints and narrates the English alone — a standalone readable edition.",
};

function updateSides() {
  const sides = $("sides").value;
  // "which language comes first" means nothing once a bead has one side.
  for (const el of document.querySelectorAll(".dual-only"))
    el.style.display = sides === "both" ? "" : "none";

  // The public-domain confirmation guards *publishing someone's translation*.
  // It is irrelevant on the corpus tab (that English is our own machine
  // translation) and irrelevant for an original-only edition, which publishes
  // no translation at all.
  const needsPd = state.source !== "corpus" && sides !== "src";
  $("pdConfirmRow").style.display = needsPd ? "" : "none";
  $("pdBanner").style.display = needsPd ? "" : "none";

  $("sidesNote").textContent = SIDES_NOTE[sides];
  if (state.corpus) renderCorpusHint();
  updateEngineNote();
}

// On the corpus tab, an original-only edition unlocks the works that have no
// English at all — so say so where the filter lives.
function renderCorpusHint() {
  const hint = $("cTranslatedHint");
  if (!hint) return;
  hint.textContent = $("sides").value === "src"
    ? "— untick this to reach untranslated works; an original-only edition can print them"
    : "";
}

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
    FONTS = (await getJSON("/api/fonts")).fonts || [];
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
  const lang = $("srcLang").value;
  const isGreek = lang === "el" || lang === "grc";
  note.textContent = (f && isGreek && f.greek === false)
    ? "⚠ This font lacks Greek glyphs — pick a ✔ Greek font." : "";
}

// --------------------------------------------------------------------------- //
// Gutenberg search
// --------------------------------------------------------------------------- //
async function doSearch() {
  const q = $("q").value.trim();
  if (!q) return;
  const box = $("results");
  box.innerHTML = `<div class="result muted">Searching…</div>`;
  try {
    const url = `/api/search?q=${encodeURIComponent(q)}&lang=${encodeURIComponent($("lang").value)}`;
    const data = await getJSON(url);
    if (!data.results.length) {
      box.innerHTML = `<div class="result muted">${escapeHtml(data.hint || "No results.")}</div>`;
      return;
    }
    box.innerHTML = "";
    for (const b of data.results) box.appendChild(resultRow(b));
  } catch (e) {
    box.innerHTML = `<div class="result">⚠ ${escapeHtml(e.message)}</div>`;
  }
}

function resultRow(b) {
  const row = document.createElement("div");
  row.className = "result";
  const txt = b.has_text ? "" : `<span class="badge">no plain text</span>`;
  row.innerHTML = `
    <div class="meta">
      <b>${escapeHtml(b.title)}</b>
      <small>${escapeHtml(b.authors)} · #${b.id} · ${b.languages.join(", ")} ${txt}</small>
    </div>
    <div class="pick">
      <button data-role="src">→ Original</button>
      <button data-role="tgt">→ Translation</button>
    </div>`;
  row.querySelector('[data-role="src"]').onclick = () => selectEdition("src", b);
  row.querySelector('[data-role="tgt"]').onclick = () => selectEdition("tgt", b);
  return row;
}

function selectEdition(which, b) {
  state[which] = { ...b };
  renderSlot(which);
  loadOutline(which);
  if (which === "src") {
    if (!$("title").value) $("title").value = b.title;
    if (!$("author").value) $("author").value = b.authors;
    const lang = (b.languages[0] || "").toLowerCase();
    if ([...$("srcLang").options].some((o) => o.value === lang)) $("srcLang").value = lang;
    updateFontNote();
  }
}

async function loadOutline(which) {
  const b = state[which];
  const box = $(which === "src" ? "range-src" : "range-tgt");
  if (!b || !b.id) { box.innerHTML = ""; return; }
  box.innerHTML = `<small class="muted">loading outline…</small>`;
  try {
    b.outline = (await getJSON(`/api/outline?id=${b.id}`)).divisions || [];
  } catch { box.innerHTML = `<small class="muted">outline unavailable</small>`; return; }
  renderRange(box, b.outline);
}

// `skipFirst` defaults a Gutenberg text past its front matter (division 1 is
// almost always a title page / preface). Corpus sections have no front matter —
// section 1 is already real content — so it starts at 1 there.
function renderRange(box, divs, skipFirst = true) {
  if (!divs || divs.length <= 1) { box.innerHTML = ""; return; }
  const opts = divs.map((d) => {
    const t = d.title.length > 30 ? d.title.slice(0, 29) + "…" : d.title;
    return `<option value="${d.index}">${d.index}. ${escapeHtml(t)}</option>`;
  }).join("");
  box.innerHTML = `<div class="rng">
      <span>from</span><select data-end="from">${opts}</select>
      <span>to</span><select data-end="to">${opts}</select></div>`;
  box.querySelector('[data-end="from"]').value = skipFirst ? "2" : "1";
  box.querySelector('[data-end="to"]').value = String(divs[divs.length - 1].index);
}

function readRange(box) {
  const from = box.querySelector('[data-end="from"]');
  const to = box.querySelector('[data-end="to"]');
  return from && to ? [parseInt(from.value, 10), parseInt(to.value, 10)] : null;
}

function getRange(which) {
  return readRange($(which === "src" ? "range-src" : "range-tgt"));
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
// Latin corpus
// --------------------------------------------------------------------------- //
async function loadCorpusStatus() {
  const el = $("corpusStatus");
  try {
    const s = await getJSON("/api/corpus/status");
    if (!s.available) { el.innerHTML = `⚠ ${escapeHtml(s.error)}`; return; }
    el.innerHTML = `${s.documents.toLocaleString()} works in
      <code>${escapeHtml(s.path)}</code> — already sentence-aligned, so a build
      from here skips fetching and alignment entirely.`;
  } catch (e) {
    el.innerHTML = `⚠ ${escapeHtml(e.message)}`;
  }
}

// Author / genre / period picklists — substring search over 13k works only
// helps if you already know the Latin form of the name you want.
async function loadFacets() {
  let f;
  try {
    f = await getJSON("/api/corpus/facets");
  } catch { return; }

  const fill = (id, items, label) => {
    const sel = $(id);
    sel.innerHTML = `<option value="">any</option>`;
    for (const it of items) {
      const o = document.createElement("option");
      o.value = it.value;
      o.textContent = `${label ? label(it.value) : it.value} (${it.count})`;
      sel.appendChild(o);
    }
  };
  fill("cAuthor", f.authors || []);
  fill("cGenre", f.genres || []);
  fill("cStage", f.stages || [], (v) => v.replace(/_/g, " "));

  const cents = (f.centuries || []).map((c) => c.value);
  if (cents.length) {
    $("cCentFrom").placeholder = `from ${Math.min(...cents)}`;
    $("cCentTo").placeholder = `to ${Math.max(...cents)}`;
  }
}

async function doCorpusSearch() {
  const box = $("cResults");
  box.innerHTML = `<div class="result muted">Searching…</div>`;
  const params = new URLSearchParams({
    q: $("cq").value.trim(),
    lang: $("cLang").value,
    author: $("cAuthor").value,
    genre: $("cGenre").value,
    stage: $("cStage").value,
    century_from: $("cCentFrom").value,
    century_to: $("cCentTo").value,
    translated: $("cTranslated").checked ? "1" : "0",
    styled: $("cStyledOnly").checked ? "1" : "0",
  });
  try {
    const data = await getJSON(`/api/corpus/search?${params}`);
    if (!data.results.length) {
      box.innerHTML = `<div class="result muted">${escapeHtml(data.hint || "No results.")}</div>`;
      return;
    }
    box.innerHTML = "";
    for (const d of data.results) box.appendChild(corpusRow(d));
  } catch (e) {
    box.innerHTML = `<div class="result">⚠ ${escapeHtml(e.message)}</div>`;
  }
}

const RISK_LABEL = { ok: "licence ok", check: "check licence", unknown: "licence unknown" };

function corpusRow(d) {
  const row = document.createElement("div");
  row.className = "result";
  const pct = Math.round(d.coverage * 100);
  row.innerHTML = `
    <div class="meta">
      <b>${escapeHtml(d.title)}</b>
      <small>${escapeHtml(d.author)} · #${d.id} · ${d.language} ·
        ${d.segments.toLocaleString()} segments · ${pct}% English
        ${d.styled ? `· ${d.styled.toLocaleString()} stylized` : ""}
        <span class="badge risk-${d.license_risk}">${RISK_LABEL[d.license_risk]}</span>
      </small>
    </div>
    <div class="pick"><button>→ Use this</button></div>`;
  row.querySelector("button").onclick = () => selectCorpusDoc(d.id);
  return row;
}

async function selectCorpusDoc(id, opts = {}) {
  const detail = $("corpusDetail");
  detail.innerHTML = `<p class="muted">Loading…</p>`;
  const prev = state.corpus && state.corpus.doc.id === id ? state.corpus : {};
  const styled = opts.preferStyled ?? prev.preferStyled ?? true;
  const strip = opts.stripMarkup ?? prev.stripMarkup ?? true;
  try {
    const data = await getJSON(
      `/api/corpus/doc/${id}?styled=${styled ? 1 : 0}&strip=${strip ? 1 : 0}`);
    state.corpus = { ...data, preferStyled: styled, stripMarkup: strip };
  } catch (e) {
    detail.innerHTML = `<p>⚠ ${escapeHtml(e.message)}</p>`;
    return;
  }
  renderCorpusPick();
}

function renderCorpusPick() {
  const c = state.corpus;
  const pick = $("corpusPick").querySelector(".slot-body");
  const detail = $("corpusDetail");
  if (!c) {
    $("corpusPick").classList.remove("filled");
    pick.className = "slot-body muted";
    pick.textContent = "none selected";
    detail.innerHTML = "";
    return;
  }
  const d = c.doc;
  $("corpusPick").classList.add("filled");
  pick.className = "slot-body";
  pick.innerHTML = `<b>${escapeHtml(d.title)}</b>
    <small class="muted">${escapeHtml(d.author)} · #${d.id} · ${d.language}
      (${escapeHtml(d.language_stage)})</small>
    <span class="clear">clear</span>`;
  pick.querySelector(".clear").onclick = () => { state.corpus = null; renderCorpusPick(); };

  // Prefill the shared options from the document record.
  $("title").value = d.title;
  $("author").value = d.author;
  if ([...$("srcLang").options].some((o) => o.value === d.language))
    $("srcLang").value = d.language;
  updateFontNote();

  const rows = c.sample.map((s) => `
    <div class="pair">
      <div class="pair-src">${escapeHtml(s.src)}</div>
      <div class="pair-tgt">${escapeHtml(s.tgt)}${s.styled ? ` <span class="badge">stylized</span>` : ""}</div>
    </div>`).join("");

  detail.innerHTML = `
    <div class="corpus-meta">
      <div><span class="k">source</span> ${escapeHtml(d.source || "—")}</div>
      <div><span class="k">licence</span>
        <span class="badge risk-${d.license_risk}">${RISK_LABEL[d.license_risk]}</span>
        ${escapeHtml(d.license || "none recorded")}</div>
      <div><span class="k">English</span> ${d.translated.toLocaleString()} of
        ${d.segments.toLocaleString()} segments${d.styled ? `, ${d.styled.toLocaleString()} stylized` : ""}</div>
    </div>
    <p class="muted small">${escapeHtml(c.note)}</p>
    <label class="inline-check"><input id="cStyled" type="checkbox"
      ${c.preferStyled ? "checked" : ""}> prefer the stylized English where it exists</label>
    <label class="inline-check"><input id="cStrip" type="checkbox"
      ${c.stripMarkup ? "checked" : ""}> strip editorial sigla
      (<code>&lt;A&gt;ltus</code> → <code>Altus</code>) — a narrator can't say a bracket</label>
    <h3>Sections</h3>
    <div class="slot-range" id="range-corpus"></div>
    <h3>Preview</h3>
    <div class="pairs">${rows || `<p class="muted">No segments.</p>`}</div>`;

  // Corpus sections have no front matter to skip, so the range starts at 1.
  renderRange($("range-corpus"),
    c.sections.map((s) => ({ index: s.index, title: `${s.title} (${s.segments})` })),
    false);
  $("cStyled").onchange =
    () => selectCorpusDoc(d.id, { preferStyled: $("cStyled").checked });
  $("cStrip").onchange =
    () => selectCorpusDoc(d.id, { stripMarkup: $("cStrip").checked });
}

// --------------------------------------------------------------------------- //
// Local files — your own .txt and .epub
// --------------------------------------------------------------------------- //
async function loadLocalFiles() {
  const box = $("localResults");
  box.innerHTML = `<div class="result muted">Reading input/…</div>`;
  let data;
  try {
    data = await getJSON("/api/local/files");
  } catch (e) {
    box.innerHTML = `<div class="result">⚠ ${escapeHtml(e.message)}</div>`;
    return;
  }
  $("localDir").textContent = data.dir;
  $("localStatus").textContent = data.files.length
    ? `${data.files.length} file(s) available.`
    : "No .txt or .epub files in input/ yet.";
  box.innerHTML = "";
  for (const f of data.files) box.appendChild(localRow(f));
}

function localRow(f) {
  const row = document.createElement("div");
  row.className = "result";
  row.innerHTML = `
    <div class="meta">
      <b>${escapeHtml(f.name)}</b>
      <small>${f.kind} · ${f.size_mb} MB</small>
    </div>
    <div class="pick">
      <button data-role="lsrc">→ Original</button>
      <button data-role="ltgt">→ Translation</button>
    </div>`;
  row.querySelector('[data-role="lsrc"]').onclick = () => selectLocal("lsrc", f);
  row.querySelector('[data-role="ltgt"]').onclick = () => selectLocal("ltgt", f);
  return row;
}

async function selectLocal(which, f) {
  state[which] = { ...f };
  renderLocalSlot(which);
  if (which === "lsrc" && !$("title").value) {
    $("title").value = f.name.replace(/\.(txt|epub)$/i, "").replace(/[_-]+/g, " ");
  }
  // Inspect before outlining: a scan with no usable text layer should be
  // reported as such rather than silently producing an empty outline.
  await inspectLocal(which);
  await loadLocalOutline(which);
}

async function inspectLocal(which) {
  const f = state[which];
  const detail = $("localDetail");
  if (!f) { detail.innerHTML = ""; return; }
  let r;
  try {
    r = await getJSON(`/api/local/inspect?path=${encodeURIComponent(f.path)}`);
  } catch (e) {
    detail.innerHTML = `<p class="warn">⚠ ${escapeHtml(e.message)}</p>`;
    return;
  }
  f.report = r;
  const warns = (r.warnings || []).map((w) =>
    `<p class="${w.startsWith("Unusable") ? "warn" : "caution"}">⚠ ${escapeHtml(w)}</p>`
  ).join("");
  detail.innerHTML = `
    <div class="corpus-meta">
      <div><span class="k">file</span> ${escapeHtml(f.name)}</div>
      <div><span class="k">text</span> ${r.characters.toLocaleString()} characters
        across ${r.documents} document(s)${r.images ? `, ${r.images} image(s)` : ""}</div>
      ${r.ocr_accuracy !== null && r.ocr_accuracy !== undefined
        ? `<div><span class="k">ocr</span> self-reported ${r.ocr_accuracy}% accurate</div>` : ""}
    </div>${warns}`;
}

async function loadLocalOutline(which) {
  const f = state[which];
  const box = $(which === "lsrc" ? "range-lsrc" : "range-ltgt");
  if (!f) { box.innerHTML = ""; return; }
  box.innerHTML = `<small class="muted">reading outline…</small>`;
  try {
    const url = `/api/local/outline?path=${encodeURIComponent(f.path)}` +
                `&mode=${encodeURIComponent($("mode").value)}`;
    f.outline = (await getJSON(url)).divisions || [];
  } catch (e) {
    box.innerHTML = `<small class="muted">outline unavailable — ${escapeHtml(e.message)}</small>`;
    return;
  }
  renderRange(box, f.outline);
}

function renderLocalSlot(which) {
  const slot = $(which === "lsrc" ? "slot-lsrc" : "slot-ltgt");
  const body = slot.querySelector(".slot-body");
  const f = state[which];
  if (!f) {
    slot.classList.remove("filled");
    body.className = "slot-body muted";
    body.textContent = "none selected";
    return;
  }
  slot.classList.add("filled");
  body.className = "slot-body";
  body.innerHTML = `<b>${escapeHtml(f.name)}</b>
    <small class="muted">${f.kind} · ${f.size_mb} MB</small>
    <span class="clear">clear</span>`;
  body.querySelector(".clear").onclick = () => {
    state[which] = null;
    renderLocalSlot(which);
    $(which === "lsrc" ? "range-lsrc" : "range-ltgt").innerHTML = "";
    $("localDetail").innerHTML = "";
  };
}

// --------------------------------------------------------------------------- //
// Build history — survives a server restart
// --------------------------------------------------------------------------- //
const STATUS_LABEL = {
  done: "done", error: "failed", running: "running",
  cancelled: "stopped", interrupted: "interrupted by a restart",
};

async function loadHistory() {
  const box = $("history");
  let data;
  try {
    data = await getJSON("/api/jobs");
  } catch { return; }
  if (!data.jobs.length) {
    box.innerHTML = `<div class="result muted">No builds yet.</div>`;
    return;
  }
  box.innerHTML = "";
  for (const j of data.jobs) {
    const row = document.createElement("div");
    row.className = "result";
    const when = new Date(j.created_at * 1000).toLocaleString();
    const bits = [STATUS_LABEL[j.status] || j.status, when];
    if (j.pages) bits.push(`${j.pages} pages`);
    if (j.audio) bits.push(j.audio);
    row.innerHTML = `
      <div class="meta">
        <b>${escapeHtml(j.title || "(untitled)")}</b>
        <small>${escapeHtml(bits.join(" · "))}</small>
      </div>
      <div class="pick">${j.has_pdf ? `<button>Open</button>` : ""}</div>`;
    const btn = row.querySelector("button");
    if (btn) btn.onclick = () => reopenJob(j.id);
    box.appendChild(row);
  }
}

async function reopenJob(jobId) {
  state.job = jobId;
  let data;
  try {
    data = await getJSON(`/api/status/${jobId}`);
  } catch (e) {
    $("log").textContent = `⚠ ${e.message}`;
    return;
  }
  $("log").textContent = data.log.join("\n");
  state.pages = data.pages;
  state.page = 0;
  $("download").href = `/api/download/${jobId}.pdf`;
  $("download").style.display = "inline-block";
  if (data.has_cover) {
    $("coverToggle").style.display = "inline-block";
    $("coverDownload").href = `/api/cover-download/${jobId}.pdf`;
    $("coverDownload").style.display = "inline-block";
  }
  showAudio(data.audio);
  showPage(0);
}

// --------------------------------------------------------------------------- //
// Audiobook settings
// --------------------------------------------------------------------------- //
let ENGINES = [];

async function loadAudio() {
  let data;
  try {
    data = await getJSON("/api/audio/engines");
  } catch { return; }
  ENGINES = data.engines || [];

  const eSel = $("auEngine");
  eSel.innerHTML = "";
  for (const e of ENGINES) {
    const o = document.createElement("option");
    o.value = e.id;
    o.textContent = `${e.label}${e.installed ? "" : "  (not installed)"}`;
    eSel.appendChild(o);
  }
  const firstInstalled = ENGINES.find((e) => e.installed);
  if (firstInstalled) eSel.value = firstInstalled.id;
  updateEngineNote();

  const dSel = $("auDevice");
  dSel.innerHTML = "";
  for (const d of data.devices || []) {
    const o = document.createElement("option");
    o.value = d.id;
    o.textContent = d.label;
    dSel.appendChild(o);
  }
  if (data.recommended) dSel.value = data.recommended;
  $("auDeviceNote").textContent = data.note || "";
}

function updateEngineNote() {
  const e = ENGINES.find((x) => x.id === $("auEngine").value);
  const note = $("auEngineNote");
  if (!e) { note.textContent = ""; return; }
  const bits = [`${e.licence}${e.clones_voice ? " · clones a voice" : " · fixed voices"}`];
  if (!e.installed) bits.push(`not installed — ${e.reason}`);
  // Latin and Ancient Greek are read with the nearest living voice; warn when
  // the chosen engine does not even have that. Only relevant if the original
  // is actually narrated — a translation-only edition never reads it.
  if ($("sides").value !== "tgt") {
    const need = { la: "it", grc: "el" }[$("srcLang").value] || $("srcLang").value;
    if (e.languages.length && !e.languages.includes(need))
      bits.push(`⚠ no '${need}' voice — the original would have nothing to read it`);
  }
  note.textContent = bits.join(" · ");
}

async function estimateAudio() {
  const out = $("auEstimate");
  out.textContent = "estimating…";
  try {
    const data = await postJSON("/api/audio/estimate", buildPayload());
    if (!data.estimate) { out.textContent = data.note; return; }
    const e = data.estimate;
    out.textContent = `${e.utterances.toLocaleString()} utterances, ` +
      `${e.characters.toLocaleString()} characters — about ${e.duration} of audio.`;
  } catch (e) {
    out.textContent = `⚠ ${e.message}`;
  }
}

function audioPayload() {
  return {
    enabled: $("auEnabled").checked,
    engine: $("auEngine").value,
    device: $("auDevice").value,
    voice: $("auVoice").value.trim() || null,
    pause_within: parseFloat($("auPauseWithin").value) || 0.45,
    pause_bead: parseFloat($("auPauseBead").value) || 0.9,
    announce_chapters: $("auAnnounce").checked,
    format: $("auFormat").value,
    max_beads: $("auMaxBeads").value ? parseInt($("auMaxBeads").value, 10) : null,
  };
}

// --------------------------------------------------------------------------- //
// Build
// --------------------------------------------------------------------------- //
function buildPayload() {
  const p = {
    title: $("title").value || "Untitled",
    author: $("author").value || "Unknown",
    src_lang: $("srcLang").value,
    mode: $("mode").value,
    aligner: $("aligner").value,
    first: $("first").value,
    sides: $("sides").value,
    font: $("font").value,
    trim: [parseFloat($("trimW").value), parseFloat($("trimH").value)],
    toc: $("tocSel").value === "yes",
    epub: $("epubEnabled").checked,
    decorations: { margin: $("margin").value, chapter: $("chapter").value },
    audio: audioPayload(),
    copyright: {
      enabled: $("cpEnabled").checked,
      publisher: $("cpPublisher").value,
      holder: $("cpHolder").value,
      year: $("cpYear").value ? parseInt($("cpYear").value, 10) : null,
      isbn: $("cpIsbn").value,
      translator: $("cpTranslator").value,
    },
    cover: {
      enabled: $("cvEnabled").checked,
      paper: $("cvPaper").value,
      blurb: $("cvBlurb").value,
    },
  };

  if (state.source === "corpus") {
    if (!state.corpus) return p;
    p.corpus_id = state.corpus.doc.id;
    p.corpus_range = readRange($("range-corpus"));
    p.prefer_styled = state.corpus.preferStyled;
    p.strip_markup = state.corpus.stripMarkup;
    // The English side is our own machine translation, so no third-party
    // translator holds copyright on it — the source licence is the thing to
    // watch, and that is surfaced on the document itself.
    p.translation_pd_confirmed = true;
  } else if (state.source === "local") {
    p.src_path = state.lsrc && state.lsrc.path;
    p.tgt_path = state.ltgt && state.ltgt.path;
    p.src_range = readRange($("range-lsrc"));
    p.tgt_range = readRange($("range-ltgt"));
    // Only the Gutenberg tab can vouch for a translation's status; a local
    // file's provenance is the user's own knowledge, and an original-only
    // edition publishes no translation at all.
    p.translation_pd_confirmed = $("sides").value === "src" || $("pd").checked;
  } else if ($("sides").value === "src") {
    p.src_id = state.src && state.src.id;
    p.tgt_id = state.tgt && state.tgt.id;
    p.src_range = getRange("src");
    p.tgt_range = getRange("tgt");
    // No translation is published in an original-only edition.
    p.translation_pd_confirmed = true;
  } else {
    p.src_id = state.src && state.src.id;
    p.tgt_id = state.tgt && state.tgt.id;
    p.src_range = getRange("src");
    p.tgt_range = getRange("tgt");
    p.translation_pd_confirmed = $("pd").checked;
  }
  return p;
}

function validate() {
  const sides = $("sides").value;
  if (state.source === "corpus") {
    if (!state.corpus) return "Pick a work from the corpus.";
    return null;
  }
  if (state.source === "local") {
    if (!state.lsrc) return "Pick an Original file.";
    if (sides !== "src" && !state.ltgt) {
      return "Pick a Translation file, or set Edition to \"original only\".";
    }
    // The quality report is advisory, but silently building a 24%-accurate
    // scan wastes a long run and produces an unreadable book.
    const bad = [state.lsrc, state.ltgt].filter(
      (f) => f && f.report && !f.report.usable);
    if (bad.length && !confirm(
        `${bad.map((f) => f.name).join(", ")} has no usable text ` +
        `(see the warning above). Build anyway?`)) {
      return "Cancelled.";
    }
    if (sides !== "src" && !$("pd").checked)
      return "Confirm the translation is public domain before building.";
    return null;
  }
  if (!state.src) return "Pick an Original edition.";
  if (!state.tgt) return "Pick a Translation edition.";
  // An original-only edition publishes no translation, so there is nothing to
  // confirm the public-domain status of.
  if ($("sides").value !== "src" && !$("pd").checked)
    return "Confirm the translation is public domain before building.";
  return null;
}

async function doBuild() {
  const problem = validate();
  if (problem) return alert(problem);

  $("buildBtn").disabled = true;
  $("log").textContent = "Queued…\n";
  resetPreview();
  try {
    const data = await postJSON("/api/build", buildPayload());
    state.job = data.job_id;
    $("cancelBtn").style.display = $("auEnabled").checked ? "inline-block" : "none";
    pollStatus();
  } catch (e) {
    $("log").textContent += `\n⚠ ${e.message}`;
    $("buildBtn").disabled = false;
  }
}

function pollStatus() {
  if (state.poll) clearInterval(state.poll);
  state.poll = setInterval(async () => {
    let data;
    try { data = await (await fetch(`/api/status/${state.job}`)).json(); }
    catch { return; }
    $("log").textContent = data.log.join("\n");
    $("log").scrollTop = $("log").scrollHeight;
    showProgress(data.progress);

    if (data.status !== "running") {
      clearInterval(state.poll);
      $("buildBtn").disabled = false;
      $("cancelBtn").style.display = "none";
      if ($("historySection").open) loadHistory();
    }
    if (data.status !== "done") return;

    state.pages = data.pages;
    state.page = 0;
    state.viewingCover = false;
    $("download").href = `/api/download/${state.job}.pdf`;
    $("download").style.display = "inline-block";
    if (data.has_cover) {
      $("coverToggle").style.display = "inline-block";
      $("coverDownload").href = `/api/cover-download/${state.job}.pdf`;
      $("coverDownload").style.display = "inline-block";
    }
    showAudio(data.audio);
    showPage(0);
  }, 700);
}

function showProgress(p) {
  const wrap = $("progressWrap");
  if (!p) { wrap.style.display = "none"; return; }
  wrap.style.display = "block";
  $("progressBar").style.width = `${p.percent}%`;
  $("progressLabel").textContent =
    `narrating ${p.done.toLocaleString()} / ${p.total.toLocaleString()} utterances (${p.percent}%)`;
}

function showAudio(audio) {
  const wrap = $("audioWrap");
  if (!audio || !audio.book) { wrap.style.display = "none"; return; }
  const ext = audio.format || "m4b";
  wrap.style.display = "block";
  $("audioPlayer").src = `/api/audio/${state.job}.${ext}`;
  $("audioDownload").href = `/api/audio/${state.job}.${ext}?dl=1`;
  $("audioLabel").textContent =
    `${audio.duration} · ${audio.chapters} chapter(s) · ${audio.engine}`;
}

async function cancelBuild() {
  if (!state.job) return;
  $("cancelBtn").disabled = true;
  try { await postJSON(`/api/cancel/${state.job}`, {}); } catch { /* ignore */ }
  $("cancelBtn").disabled = false;
}

// --------------------------------------------------------------------------- //
// Preview
// --------------------------------------------------------------------------- //
function resetPreview() {
  state.pages = 0;
  state.viewingCover = false;
  $("previewWrap").innerHTML = `<p class="muted">Building…</p>`;
  $("pageLabel").textContent = "— / —";
  $("audioWrap").style.display = "none";
  $("progressWrap").style.display = "none";
  for (const id of ["download", "coverToggle", "coverDownload"])
    $(id).style.display = "none";
}

function showPage(i) {
  if (!state.job || state.pages === 0) return;
  state.viewingCover = false;
  $("coverToggle").textContent = "View cover";
  state.page = Math.max(0, Math.min(i, state.pages - 1));
  const url = `/api/preview/${state.job}/${state.page}.png?t=${Date.now()}`;
  $("previewWrap").innerHTML = `<img alt="page ${state.page + 1}" src="${url}">`;
  $("pageLabel").textContent = `${state.page + 1} / ${state.pages}`;
}

function toggleCover() {
  if (state.viewingCover) { showPage(state.page); return; }
  state.viewingCover = true;
  $("coverToggle").textContent = "View interior";
  $("previewWrap").innerHTML =
    `<img alt="cover" src="/api/cover/${state.job}.png?t=${Date.now()}">`;
  $("pageLabel").textContent = "cover";
}

async function saveConfig() {
  const problem = validate();
  if (problem) return alert(problem);
  try {
    const data = await postJSON("/api/save-config", buildPayload());
    const n = data.count;
    $("log").textContent =
      `✓ Saved to ${data.saved} — ${n} book${n === 1 ? "" : "s"} in config. ` +
      `Build the whole file with: python make_book.py ${data.saved}`;
  } catch (e) {
    $("log").textContent = `⚠ ${e.message}`;
  }
}

// --------------------------------------------------------------------------- //
// Wire up
// --------------------------------------------------------------------------- //
for (const t of document.querySelectorAll(".tab"))
  t.onclick = () => selectTab(t.dataset.tab);

$("searchBtn").onclick = doSearch;
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
$("cSearchBtn").onclick = doCorpusSearch;
$("cq").addEventListener("keydown", (e) => { if (e.key === "Enter") doCorpusSearch(); });
$("localRefresh").onclick = loadLocalFiles;
$("historySection").addEventListener("toggle", (e) => {
  if (e.target.open) loadHistory();
});
$("buildBtn").onclick = doBuild;
$("saveBtn").onclick = saveConfig;
$("cancelBtn").onclick = cancelBuild;
$("coverToggle").onclick = toggleCover;
$("auEstimateBtn").onclick = estimateAudio;
$("auEngine").addEventListener("change", updateEngineNote);
$("sides").addEventListener("change", updateSides);
$("font").addEventListener("change", updateFontNote);
$("srcLang").addEventListener("change", () => { updateFontNote(); updateEngineNote(); });
$("prev").onclick = () => showPage(state.page - 1);
$("next").onclick = () => showPage(state.page + 1);
document.addEventListener("keydown", (e) => {
  const tag = e.target.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (e.key === "ArrowLeft") showPage(state.page - 1);
  if (e.key === "ArrowRight") showPage(state.page + 1);
});

selectTab("gutenberg");
loadFonts();
loadCorpusStatus();
loadFacets();
loadLocalFiles();
loadAudio();
