// DataSentry frontend. Every string that comes from a dataset (column names, values, labels) is
// inserted as text through createElement/textContent; innerHTML is never used.
"use strict";

const SEVERITIES = ["high", "medium", "low", "info"];
const KINDS = ["likely_issue", "potential_issue", "observation", "inconclusive"];
const CATEGORIES = ["completeness", "uniqueness", "column_quality", "consistency", "distribution", "target", "leakage"];
const TYPES = ["numeric", "categorical", "boolean", "datetime", "text", "empty"];
const STATUS_TEXT = {
  issues_detected: "Issues detected",
  review_recommended: "Review recommended",
  no_issues_detected: "No issues detected",
  issue: "Issue",
  review: "Review",
  pass: "Pass",
  not_evaluated: "Not evaluated",
};

const state = {
  limits: null,
  file: null,
  sample: null,
  result: null,
  selectedColumn: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);

// --- DOM helpers ---------------------------------------------------------------------------

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  return put(el, ...children);
}

// Appends children like h() does: nested arrays are flattened, null/undefined/false are skipped
// (plain Element.append would insert them as the text "null"), and strings become text nodes.
function put(parent, ...children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : String(child));
  }
  return parent;
}

function clear(el) {
  el.replaceChildren();
  return el;
}

const label = (key) => key.replaceAll("_", " ");
const fmtInt = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString());
const fmtPct = (f, digits = 1) => (f === null || f === undefined ? "—" : `${(f * 100).toFixed(digits)}%`);
function fmtNum(x) {
  if (x === null || x === undefined) return "—";
  if (Number.isInteger(x) && Math.abs(x) < 1e15) return x.toLocaleString();
  const abs = Math.abs(x);
  if (abs !== 0 && (abs >= 1e6 || abs < 1e-3)) return x.toExponential(3);
  return Number(x.toPrecision(5)).toLocaleString(undefined, { maximumFractionDigits: 6 });
}
function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function pill(text, cls) {
  return h("span", { class: `pill ${cls}`, text });
}
const severityPill = (s) => pill(s, `dot sev-${s}`);
const kindPill = (k) => pill(label(k), "pill-outline");

function bar(fraction, warn) {
  const fill = h("span");
  fill.style.width = `${Math.max(0, Math.min(1, fraction)) * 100}%`;
  return h("div", { class: warn ? "bar warn" : "bar", role: "presentation" }, fill);
}

function barRow(name, fraction, valueText, warn) {
  return h("div", { class: "bar-row" },
    h("span", { class: "bar-label", title: name, text: name }),
    bar(fraction, warn),
    h("span", { class: "bar-value", text: valueText }));
}

function emptyState(text) {
  return h("div", { class: "empty-state", text });
}

let toastTimer;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

// --- API -----------------------------------------------------------------------------------

class ApiError extends Error {
  constructor(message, code, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function errorFromResponse(status, body) {
  if (body && typeof body.message === "string") return new ApiError(body.message, body.error, status);
  if (status === 413) return new ApiError("The file is larger than the server accepts.", "file_too_large", status);
  if (status >= 500) return new ApiError("The server hit an unexpected error. Try again.", "internal_error", status);
  return new ApiError(`The request failed (HTTP ${status}).`, "http_error", status);
}

function parseJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

// XHR is used for the main upload because fetch does not report upload progress.
function postWithProgress(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.responseType = "text";
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress("upload", e.loaded / e.total);
    });
    xhr.upload.addEventListener("load", () => onProgress("processing"));
    xhr.addEventListener("load", () => {
      const body = parseJson(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300 && body) resolve(body);
      else reject(errorFromResponse(xhr.status, body));
    });
    xhr.addEventListener("error", () => reject(new ApiError("Could not reach the DataSentry server. Is it running?", "network_error", 0)));
    xhr.send(form);
  });
}

async function post(path, form) {
  let response;
  try {
    response = await fetch(path, { method: "POST", body: form });
  } catch {
    throw new ApiError("Could not reach the DataSentry server. Is it running?", "network_error", 0);
  }
  if (!response.ok) throw errorFromResponse(response.status, parseJson(await response.text()));
  return response;
}

function baseForm(extra) {
  const form = new FormData();
  form.append("file", state.file, state.file.name);
  const target = state.result?.settings.target_column;
  if (target) form.append("target_column", target);
  for (const [k, v] of Object.entries(extra || {})) form.set(k, v);
  return form;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function filenameFrom(response, fallback) {
  const match = /filename="([A-Za-z0-9._-]+)"/.exec(response.headers.get("content-disposition") || "");
  return match ? match[1] : fallback;
}

// --- Upload flow ---------------------------------------------------------------------------

function setUploadBusy(busy, text) {
  state.busy = busy;
  $("dropzone").classList.toggle("is-disabled", busy);
  $("upload-progress").hidden = !busy;
  document.querySelectorAll("[data-sample]").forEach((b) => { b.disabled = busy; });
  if (text) $("progress-label").textContent = text;
}

function showUploadError(err) {
  const box = clear($("upload-error"));
  put(box, h("span", { class: "alert-title", text: "This file could not be analyzed" }), err.message);
  box.hidden = false;
}

function validateLocally(file) {
  // Convenience only: the server enforces every limit independently.
  if (!/\.csv$/i.test(file.name)) return "Only .csv files are supported. Export spreadsheets as CSV first.";
  if (file.size === 0) return "The file is empty.";
  if (state.limits && file.size > state.limits.max_upload_bytes) {
    return `The file is ${fmtBytes(file.size)}; the limit is ${fmtBytes(state.limits.max_upload_bytes)}.`;
  }
  return null;
}

async function startAnalysis(file, { target = null, sample = null } = {}) {
  if (state.busy) return;
  $("upload-error").hidden = true;
  const problem = validateLocally(file);
  if (problem) {
    showUploadError(new ApiError(problem));
    return;
  }
  const form = new FormData();
  form.append("file", file, file.name);
  if (target) form.append("target_column", target);
  setUploadBusy(true, "Uploading…");
  const fill = $("progress-fill");
  fill.classList.remove("is-indeterminate");
  fill.style.width = "0%";
  $("progress-value").textContent = "";
  try {
    const result = await postWithProgress("/api/analyze", form, (phase, fraction) => {
      if (phase === "upload") {
        fill.style.width = `${Math.round(fraction * 100)}%`;
        $("progress-value").textContent = `${Math.round(fraction * 100)}%`;
      } else {
        $("progress-label").textContent = "Analyzing…";
        $("progress-value").textContent = "";
        fill.classList.add("is-indeterminate");
      }
    });
    state.file = file;
    state.sample = sample;
    state.selectedColumn = null;
    showDashboard(result);
  } catch (err) {
    showUploadError(err);
  } finally {
    setUploadBusy(false);
    $("file-input").value = "";
  }
}

async function loadSample(name, target) {
  try {
    const response = await fetch(`/samples/${encodeURIComponent(name)}`);
    if (!response.ok) throw new ApiError("The sample file could not be loaded.");
    const blob = await response.blob();
    await startAnalysis(new File([blob], name, { type: "text/csv" }), { target, sample: name });
  } catch (err) {
    showUploadError(err instanceof ApiError ? err : new ApiError("The sample file could not be loaded."));
  }
}

function resetToUpload() {
  state.file = null;
  state.result = null;
  state.sample = null;
  $("dashboard").hidden = true;
  $("upload-view").hidden = false;
  $("new-analysis").hidden = true;
  $("upload-error").hidden = true;
  clear($("label-review-results"));
  clear($("overlap-results"));
  window.scrollTo(0, 0);
  $("dropzone").focus();
}

async function rerun(target) {
  if (state.busy) return;
  setDashboardBusy(true);
  const form = new FormData();
  form.append("file", state.file, state.file.name);
  if (target) form.append("target_column", target);
  try {
    const result = await (await post("/api/analyze", form)).json();
    showDashboard(result, { keepTab: true });
    toast(target ? `Target analysis updated for "${target}".` : "Target cleared.");
  } catch (err) {
    toast(err.message);
  } finally {
    setDashboardBusy(false);
  }
}

function setDashboardBusy(busy) {
  state.busy = busy;
  $("dashboard-busy").hidden = !busy;
  for (const id of ["run-target", "download-json", "download-html", "new-analysis"]) {
    $(id).disabled = busy;
  }
  $("run-label-review").disabled = busy || !canReviewLabels();
}

function canReviewLabels() {
  return state.result?.target?.task === "classification";
}

// --- Dashboard -----------------------------------------------------------------------------

function showDashboard(result, { keepTab = false } = {}) {
  state.result = result;
  $("upload-view").hidden = true;
  $("dashboard").hidden = false;
  $("new-analysis").hidden = false;
  clear($("label-review-results"));
  clear($("overlap-results"));
  renderFileBar(result);
  renderSummary(result);
  renderOverview(result);
  setupFindingFilters(result);
  renderFindings();
  setupColumnFilters();
  renderColumns();
  renderMissing(result);
  renderDuplicates(result);
  renderTarget(result);
  renderMl();
  renderCorrections(result);
  $("count-findings").textContent = String(result.findings.length);
  $("count-columns").textContent = String(result.dataset.n_columns);
  $("count-corrections").textContent = result.corrections.length ? String(result.corrections.length) : "";
  if (!keepTab) selectTab("tab-findings");
  if (!keepTab) window.scrollTo(0, 0);
}

function renderFileBar(r) {
  $("file-name").textContent = r.dataset.filename;
  $("file-meta").textContent =
    `${fmtInt(r.dataset.n_rows)} rows · ${fmtInt(r.dataset.n_columns)} columns · ` +
    `${fmtBytes(r.dataset.size_bytes)} · SHA-256 ${r.dataset.sha256.slice(0, 12)}…`;
  const banner = $("partial-banner");
  const failed = r.stages.filter((s) => s.status !== "completed");
  banner.hidden = r.status === "complete";
  if (!banner.hidden) {
    put(clear(banner),
      h("span", { class: "alert-title", text: "Partial analysis" }),
      `These stages did not complete: ${failed.map((s) => `${s.name} (${s.status})`).join(", ")}. ` +
      "Results from them are missing; the rest of the report is still valid.");
  }
}

function renderSummary(r) {
  const s = r.summary;
  const status = $("summary-status");
  status.className = `status-pill st-${s.status === "issues_detected" ? "issue" : s.status === "review_recommended" ? "review" : "pass"}`;
  status.textContent = STATUS_TEXT[s.status];
  $("summary-target").textContent = r.settings.target_column
    ? `Target: ${r.settings.target_column}` : "No target selected";
  $("summary-headline").textContent = s.headline;
  put(clear($("severity-counts")),
    ...s.severity_counts.map((c) =>
      h("span", { class: `pill dot ${c.count ? `sev-${c.severity}` : "is-zero"}` }, `${c.count} ${c.severity}`)));
  put(clear($("not-evaluated")), ...s.not_evaluated.map((n) => h("li", { text: n })));
  $("score-policy").textContent = s.score_policy;
  put(clear($("category-grid")), ...s.categories.map((c) =>
    h("button", {
      type: "button",
      class: "category-cell",
      title: "Show findings in this category",
      onclick: () => {
        $("filter-category").value = c.category;
        renderFindings();
        selectTab("tab-findings");
      },
    },
    h("span", { class: "category-name", text: label(c.category) }),
    h("span", {}, h("span", { class: `status-pill st-${c.status}`, text: STATUS_TEXT[c.status] })),
    h("span", { class: "small muted", text: `${c.n_findings} finding${c.n_findings === 1 ? "" : "s"}` }))));
}

function statCard(labelText, value, sub, extraClass) {
  return h("div", { class: `card stat ${extraClass || ""}` },
    h("div", { class: "stat-label", text: labelText }),
    h("div", { class: "stat-value", text: value }),
    sub ? h("div", { class: "stat-sub", text: sub }) : null);
}

function renderOverview(r) {
  const o = r.overview;
  const cards = [
    statCard("Rows", fmtInt(o.n_rows)),
    statCard("Columns", fmtInt(o.n_columns)),
    statCard("Missing cells", fmtPct(o.missing_cell_fraction), `${fmtInt(o.n_missing_cells)} of ${fmtInt(o.n_cells)}`),
    statCard("Rows with missing values", fmtInt(o.n_rows_with_missing), fmtPct(o.rows_with_missing_fraction)),
    statCard("Duplicate rows", r.duplicates ? fmtInt(r.duplicates.n_duplicate_rows) : "—",
      r.duplicates ? fmtPct(r.duplicates.duplicate_fraction) : "not evaluated"),
    statCard("Memory (approx.)", fmtBytes(o.memory_bytes), "as loaded by pandas"),
  ];
  if (o.type_counts) {
    const total = o.type_counts.reduce((a, t) => a + t.n_columns, 0) || 1;
    const present = o.type_counts.filter((t) => t.n_columns > 0);
    const typeBar = h("div", { class: "type-bar", role: "presentation" }, present.map((t) => {
      const seg = h("span", { class: `t-${t.inferred_type}`, title: `${t.inferred_type}: ${t.n_columns}` });
      seg.style.width = `${(t.n_columns / total) * 100}%`;
      return seg;
    }));
    cards.push(h("div", { class: "card stat stat-wide" },
      h("div", { class: "stat-label", text: "Column types (inferred)" }),
      typeBar,
      h("div", { class: "type-legend" }, present.map((t) =>
        h("span", {}, h("span", { class: `swatch t-${t.inferred_type}` }), `${t.inferred_type} ${t.n_columns}`)))));
  }
  put(clear($("overview-cards")), ...cards);
}

// --- Findings ------------------------------------------------------------------------------

function fillSelect(select, allLabel, values, current) {
  put(clear(select), h("option", { value: "", text: allLabel }),
    ...values.map((v) => h("option", { value: v, text: label(v) })));
  select.value = values.includes(current) ? current : "";
}

function setupFindingFilters(r) {
  const present = (key, order) => order.filter((v) => r.findings.some((f) => f[key] === v));
  fillSelect($("filter-severity"), "All severities", present("severity", SEVERITIES), $("filter-severity").value);
  fillSelect($("filter-category"), "All categories", present("category", CATEGORIES), $("filter-category").value);
  fillSelect($("filter-kind"), "All evidence types", present("kind", KINDS), $("filter-kind").value);
}

function renderFindings() {
  const r = state.result;
  const q = $("finding-search").value.trim().toLowerCase();
  const sev = $("filter-severity").value;
  const cat = $("filter-category").value;
  const kind = $("filter-kind").value;
  let items = r.findings.filter((f) =>
    (!sev || f.severity === sev) && (!cat || f.category === cat) && (!kind || f.kind === kind) &&
    (!q || f.title.toLowerCase().includes(q) || f.code.includes(q) ||
      f.columns.some((c) => c.toLowerCase().includes(q))));
  const sort = $("sort-findings").value;
  if (sort === "category") {
    items = [...items].sort((a, b) => CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category));
  } else if (sort === "column") {
    items = [...items].sort((a, b) => (a.columns[0] || "￿").localeCompare(b.columns[0] || "￿"));
  }
  const list = clear($("findings-list"));
  if (!r.findings.length) {
    put(list, emptyState("No findings. The checks that ran found nothing to report; see the summary for checks that did not run."));
    return;
  }
  if (!items.length) {
    put(list, emptyState("No findings match these filters."));
    return;
  }
  items.forEach((f, i) => put(list, findingCard(f, `finding-${i}`)));
}

function columnChip(name) {
  const known = state.result?.columns?.some((c) => c.name === name);
  if (!known) return h("span", { class: "chip", title: name, text: name });
  return h("button", {
    type: "button", class: "chip", title: `Open column ${name}`,
    onclick: () => openColumn(name),
  }, name);
}

function findingCard(f, id) {
  const bodyId = `${id}-body`;
  const body = h("div", { class: "finding-body", id: bodyId, hidden: true },
    h("dl", { class: "detail-list" },
      h("dt", { text: "What was found" }), h("dd", { text: f.explanation }),
      h("dt", { text: "Affected columns" }),
      h("dd", {}, f.columns.length ? f.columns.map(columnChip) : "Whole dataset"),
      h("dt", { text: "Why it matters" }), h("dd", { text: f.why_it_matters }),
      h("dt", { text: "Recommended next step" }), h("dd", { text: f.recommendation }),
      f.limitations ? [h("dt", { text: "Limitations" }), h("dd", { text: f.limitations })] : null,
      h("dt", { text: "Evidence" }),
      h("dd", {}, Object.keys(f.evidence).length
        ? h("table", { class: "evidence-table" }, h("tbody", {}, Object.entries(f.evidence).map(([k, v]) =>
          h("tr", {}, h("td", { text: k }), h("td", { text: typeof v === "number" ? fmtNum(v) : String(v) })))))
        : "—"),
      h("dt", { text: "Finding code" }), h("dd", {}, h("code", { text: f.code })),
      f.correction ? [h("dt", { text: "Correction" }), h("dd", {},
        h("button", { type: "button", class: "btn btn-small", onclick: () => selectTab("tab-corrections") },
          "Review proposed correction"))] : null));
  const head = h("button", {
    type: "button", class: "finding-head", "aria-expanded": "false", "aria-controls": bodyId,
    onclick: () => {
      const open = head.getAttribute("aria-expanded") === "true";
      head.setAttribute("aria-expanded", String(!open));
      body.hidden = open;
    },
  },
  h("div", {},
    h("div", { class: "finding-tags" }, severityPill(f.severity), kindPill(f.kind), pill(label(f.category), "pill-outline")),
    h("div", { class: "finding-title", text: f.title }),
    h("div", { class: "finding-sub", text: f.explanation })),
  chevron());
  return h("article", { class: `finding sev-border-${f.severity}` }, head, body);
}

function chevron() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", "chevron");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M4 6l4 4 4-4");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.6");
  put(svg, path);
  return svg;
}

// --- Columns -------------------------------------------------------------------------------

function setupColumnFilters() {
  const cols = state.result.columns || [];
  fillSelect($("filter-type"), "All types", TYPES.filter((t) => cols.some((c) => c.inferred_type === t)), $("filter-type").value);
}

function columnFlags(c) {
  return [
    c.all_missing && "all missing",
    c.is_constant && "constant",
    c.identifier_like && "identifier-like",
    c.numeric?.n_infinite && "infinite values",
    c.categorical?.n_variant_groups && "variants",
  ].filter(Boolean);
}

function renderColumns() {
  const cols = state.result.columns;
  const tbody = clear($("columns-table").tBodies[0]);
  if (!cols) {
    put(tbody, h("tr", {}, h("td", { colspan: "5", text: "Column profiling did not complete." })));
    clear($("column-detail"));
    return;
  }
  const q = $("column-search").value.trim().toLowerCase();
  const type = $("filter-type").value;
  const shown = cols.filter((c) => (!q || c.name.toLowerCase().includes(q)) && (!type || c.inferred_type === type));
  for (const c of shown) {
    const row = h("tr", {
      class: `is-clickable${state.selectedColumn === c.name ? " is-selected" : ""}`,
      tabindex: "0",
      "aria-selected": state.selectedColumn === c.name ? "true" : "false",
      onclick: () => openColumn(c.name, false),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openColumn(c.name, false); } },
    },
    h("td", { class: "cell-name", text: c.name }),
    h("td", { text: c.inferred_type }),
    h("td", { class: "num", text: c.n_missing ? fmtPct(c.missing_fraction) : "0" }),
    h("td", { class: "num", text: fmtInt(c.n_unique) }),
    h("td", {}, columnFlags(c).map((flag) => pill(flag, "pill-outline"))));
    put(tbody, row);
  }
  if (!shown.length) put(tbody, h("tr", {}, h("td", { colspan: "5", text: "No columns match." })));
  const selected = cols.find((c) => c.name === state.selectedColumn) || shown[0] || cols[0];
  renderColumnDetail(selected);
}

function openColumn(name, switchTab = true) {
  state.selectedColumn = name;
  if (switchTab) {
    $("column-search").value = "";
    $("filter-type").value = "";
    selectTab("tab-columns");
  }
  renderColumns();
  if (switchTab) $("column-detail").scrollIntoView({ block: "nearest" });
}

function kv(labelText, value) {
  return h("div", { class: "kv" }, h("span", { text: labelText }), h("b", { text: value }));
}

function rangePlot(n) {
  if (n.min === null || n.max === null || n.max === n.min) return null;
  const pos = (v) => `${((v - n.min) / (n.max - n.min)) * 100}%`;
  const plot = h("div", { class: "range-plot", role: "img",
    "aria-label": `Range ${fmtNum(n.min)} to ${fmtNum(n.max)}, interquartile range ${fmtNum(n.q1)} to ${fmtNum(n.q3)}, median ${fmtNum(n.median)}` });
  const box = h("div", { class: "box" });
  box.style.left = pos(n.q1);
  box.style.width = `calc(${pos(n.q3)} - ${pos(n.q1)})`;
  const median = h("div", { class: "median" });
  median.style.left = pos(n.median);
  const start = h("span", { class: "label start", text: fmtNum(n.min) });
  start.style.left = "0";
  const end = h("span", { class: "label end", text: fmtNum(n.max) });
  end.style.left = "100%";
  put(plot, h("div", { class: "track" }), box, median, start, end);
  return plot;
}

function renderColumnDetail(c) {
  const panel = clear($("column-detail"));
  if (!c) return;
  put(panel,
    h("h2", { text: c.name }),
    h("p", { class: "small muted", text: `Column ${c.position + 1} · ${c.inferred_type} · pandas dtype ${c.pandas_dtype}` }),
    h("div", { class: "kv-grid" },
      kv("Non-missing", fmtInt(c.n_non_null)),
      kv("Missing", `${fmtInt(c.n_missing)} (${fmtPct(c.missing_fraction)})`),
      kv("Distinct", fmtInt(c.n_unique)),
      kv("Distinct ratio", fmtPct(c.unique_fraction)),
      kv("Most common share", fmtPct(c.dominant_fraction))));
  const related = state.result.findings.filter((f) => f.columns.includes(c.name));
  if (c.numeric) {
    const n = c.numeric;
    put(panel, h("div", { class: "section-label", text: "Distribution" }), rangePlot(n),
      h("div", { class: "kv-grid" },
        kv("Min", fmtNum(n.min)), kv("5th pct", fmtNum(n.p05)), kv("Q1", fmtNum(n.q1)),
        kv("Median", fmtNum(n.median)), kv("Q3", fmtNum(n.q3)), kv("95th pct", fmtNum(n.p95)),
        kv("Max", fmtNum(n.max)), kv("Mean", fmtNum(n.mean)), kv("Std dev", fmtNum(n.std)),
        kv("Zeros", fmtInt(n.n_zeros)), kv("Negative", fmtInt(n.n_negative)), kv("Infinite", fmtInt(n.n_infinite))),
      h("div", { class: "section-label", text: "Outlier candidates (IQR × 1.5)" }),
      n.outliers.status === "computed"
        ? h("p", { class: "small", text: `${fmtInt(n.outliers.n_below)} below ${fmtNum(n.outliers.lower_fence)}, ` +
          `${fmtInt(n.outliers.n_above)} above ${fmtNum(n.outliers.upper_fence)} (${fmtPct(n.outliers.fraction)} of values). ` +
          "Candidates for review, not errors." })
        : h("p", { class: "small muted", text: `Not computed: ${n.outliers.reason}` }));
  }
  if (c.categorical) {
    const s = c.categorical;
    put(panel, h("div", { class: "section-label", text: `Most frequent values${s.top_values_truncated ? ` (top ${s.top_values.length} of ${fmtInt(s.n_unique)})` : ""}` }),
      h("div", { class: "bar-list" }, s.top_values.map((v) =>
        barRow(v.value === "" ? "(empty string)" : v.value, v.fraction, `${fmtInt(v.count)} · ${fmtPct(v.fraction)}`))),
      h("div", { class: "kv-grid" },
        kv("Rare categories", s.n_rare_categories === null ? "not evaluated" : fmtInt(s.n_rare_categories)),
        kv("Rows in rare", fmtPct(s.rare_rows_fraction)),
        kv("Whitespace values", fmtInt(s.n_whitespace_values)),
        kv("Numeric-like", fmtInt(s.n_numeric_like)),
        kv("Mean length", fmtNum(s.mean_length)),
        kv("Max length", fmtInt(s.max_length))));
    if (s.variant_groups.length) {
      put(panel, h("div", { class: "section-label", text: "Values that differ only in case or spacing" }),
        ...s.variant_groups.map((g) => h("div", {},
          g.variants.map((v) => h("span", { class: "chip", title: JSON.stringify(v), text: JSON.stringify(v) })),
          h("span", { class: "small muted", text: `${fmtInt(g.n_rows)} rows` }))));
    }
  }
  if (c.datetime) {
    put(panel, h("div", { class: "kv-grid" },
      kv("Earliest", c.datetime.min || "—"), kv("Latest", c.datetime.max || "—"),
      kv("Unparseable", fmtInt(c.datetime.n_unparseable))));
  }
  put(panel, h("div", { class: "section-label", text: `Findings for this column (${related.length})` }),
    related.length
      ? h("div", { class: "findings-list" }, related.map((f, i) => findingCard(f, `col-finding-${i}`)))
      : h("p", { class: "small muted", text: "None." }));
}

// --- Missing values and duplicates ---------------------------------------------------------

function renderMissing(r) {
  const panel = clear($("panel-missing"));
  const o = r.overview;
  put(panel, h("div", { class: "two-col" },
    h("div", { class: "card" },
      h("h2", { class: "card-title", text: "Rows" }),
      h("div", { class: "big-number", text: fmtInt(o.n_rows_with_missing) }),
      h("p", { class: "small muted", text: `rows (${fmtPct(o.rows_with_missing_fraction)}) have at least one missing value` })),
    h("div", { class: "card" },
      h("h2", { class: "card-title", text: "Cells" }),
      h("div", { class: "big-number", text: fmtPct(o.missing_cell_fraction) }),
      h("p", { class: "small muted", text: `${fmtInt(o.n_missing_cells)} of ${fmtInt(o.n_cells)} cells are missing` }))));
  if (!r.columns) return;
  const cols = r.columns.filter((c) => c.n_missing > 0).sort((a, b) => b.missing_fraction - a.missing_fraction || a.position - b.position);
  put(panel, h("div", { class: "card", style: null },
    h("h2", { class: "card-title", text: "Missing values by column" }),
    cols.length
      ? h("div", { class: "bar-list" }, cols.map((c) =>
        barRow(c.name, c.missing_fraction, `${fmtPct(c.missing_fraction)} · ${fmtInt(c.n_missing)}`, c.missing_fraction >= 0.5)))
      : h("p", { class: "muted", text: "No column has missing values." }),
    h("p", { class: "small muted", text: "Empty cells and tokens such as NA, N/A, null and NaN are counted as missing." })));
  panel.lastChild.style.marginTop = "16px";
}

function renderDuplicates(r) {
  const panel = clear($("panel-duplicates"));
  const d = r.duplicates;
  const dupCard = h("div", { class: "card" }, h("h2", { class: "card-title", text: "Exact duplicate rows" }));
  if (!d) {
    put(dupCard, h("p", { class: "muted", text: "Duplicate detection did not complete." }));
  } else {
    put(dupCard,
      h("div", { class: "big-number", text: fmtInt(d.n_duplicate_rows) }),
      h("p", { class: "small muted", text: `${fmtPct(d.duplicate_fraction)} of rows · ${fmtInt(d.n_duplicate_groups)} distinct repeated records` }),
      d.example_row_indices.length
        ? h("p", { class: "small" }, "First repeats at row positions: ",
          d.example_row_indices.map((i) => h("span", { class: "chip", text: String(i) })))
        : null,
      h("p", { class: "small muted", text: `${d.semantics} Row positions count data rows from 0, excluding the header.` }));
  }
  const red = r.redundancy;
  const redCard = h("div", { class: "card" }, h("h2", { class: "card-title", text: "Redundant columns" }));
  if (!red) {
    put(redCard, h("p", { class: "muted", text: "Redundancy screening did not run." }));
  } else {
    put(redCard, h("div", { class: "section-label", text: "Identical columns" }),
      red.duplicate_column_groups.length
        ? h("div", {}, red.duplicate_column_groups.map((g) => h("div", {}, g.map(columnChip))))
        : h("p", { class: "small muted", text: "None." }),
      h("div", { class: "section-label", text: "Numeric pairs with |r| ≥ 0.99" }),
      red.correlated_pairs.length
        ? h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
          h("thead", {}, h("tr", {}, h("th", { text: "Column A" }), h("th", { text: "Column B" }), h("th", { class: "num", text: "Pearson r" }), h("th", { class: "num", text: "Rows" }))),
          h("tbody", {}, red.correlated_pairs.map((p) => h("tr", {},
            h("td", {}, columnChip(p.column_a)), h("td", {}, columnChip(p.column_b)),
            h("td", { class: "num", text: p.pearson_r.toFixed(4) }), h("td", { class: "num", text: fmtInt(p.n_pairs) }))))))
        : h("p", { class: "small muted", text: red.correlation_status === "skipped" ? red.correlation_note : "None." }));
  }
  put(panel, h("div", { class: "two-col" }, dupCard, redCard));
}

// --- Target --------------------------------------------------------------------------------

function renderTarget(r) {
  const select = clear($("target-select"));
  put(select, h("option", { value: "", text: "No target" }),
    ...(r.columns || []).map((c) => h("option", { value: c.name, text: `${c.name} (${c.inferred_type})` })));
  select.value = r.settings.target_column || "";
  const out = clear($("target-results"));
  const t = r.target;
  if (!r.settings.target_column) {
    put(out, emptyState("Select a target column to check class balance, label conflicts and leakage signals."));
    return;
  }
  if (!t) {
    put(out, emptyState("Target analysis did not complete for this column."));
    return;
  }
  const cards = [h("div", { class: "card" },
    h("h2", { class: "card-title", text: "Task" }),
    h("p", {}, h("strong", { text: t.task }), " · ", `${fmtInt(t.n_labeled)} labeled, ${fmtInt(t.n_missing_labels)} missing`),
    h("p", { class: "small muted", text: t.task_reason }))];
  if (t.classes) {
    const c = t.classes;
    cards.push(h("div", { class: "card" },
      h("h2", { class: "card-title", text: `Class distribution (${fmtInt(c.n_classes)} classes)` }),
      h("div", { class: "bar-list" }, c.classes.map((k) =>
        barRow(k.label, k.fraction, `${fmtInt(k.count)} · ${fmtPct(k.fraction)}`, k.count < c.rare_class_threshold))),
      c.truncated ? h("p", { class: "small muted", text: `Showing the ${c.classes.length} largest classes.` }) : null,
      h("div", { class: "kv-grid" },
        kv("Majority class size", fmtInt(c.majority_count)),
        kv("Minority class size", fmtInt(c.minority_count)),
        kv("Imbalance ratio", c.imbalance_ratio === null ? "—" : `${c.imbalance_ratio.toFixed(2)} : 1`),
        kv(`Classes < ${c.rare_class_threshold} rows`, fmtInt(c.n_rare_classes))),
      h("p", { class: "small muted", text: "Imbalance is reported as an observation. It is not a defect by itself, but it changes which metrics are meaningful." })));
  }
  if (t.regression) {
    const n = t.regression;
    cards.push(h("div", { class: "card" }, h("h2", { class: "card-title", text: "Target distribution" }), rangePlot(n),
      h("div", { class: "kv-grid" }, kv("Min", fmtNum(n.min)), kv("Median", fmtNum(n.median)), kv("Max", fmtNum(n.max)),
        kv("Mean", fmtNum(n.mean)), kv("Std dev", fmtNum(n.std)), kv("Infinite", fmtInt(n.n_infinite)))));
  }
  if (t.label_conflicts) {
    const lc = t.label_conflicts;
    cards.push(h("div", { class: "card" }, h("h2", { class: "card-title", text: "Label conflicts" }),
      h("p", {}, `${fmtInt(lc.n_conflicting_groups)} groups of identical feature rows with different labels (${fmtInt(lc.n_rows_involved)} rows).`),
      lc.example_row_indices.length ? h("p", { class: "small" }, "Example row positions: ", lc.example_row_indices.map((i) => h("span", { class: "chip", text: String(i) }))) : null));
  }
  if (t.task !== "unsupported") {
    cards.push(h("div", { class: "card" }, h("h2", { class: "card-title", text: "Leakage signals" }),
      t.leakage_signals.length
        ? h("div", {}, t.leakage_signals.map((s) => h("p", {}, columnChip(s.column), h("span", { class: "small", text: ` ${s.description}` }))))
        : h("p", { class: "small muted", text: "No feature predicts the target strongly enough to trigger a leakage screen. This does not rule out leakage." })));
  }
  put(out, h("div", { class: "two-col" }, cards));
}

// --- ML checks -----------------------------------------------------------------------------

function renderMl() {
  const ok = canReviewLabels();
  $("run-label-review").disabled = !ok; // busy state is applied by setDashboardBusy
  $("label-review-hint").textContent = ok
    ? `Uses up to ${fmtInt(state.limits?.max_label_review_rows || 0)} rows. Runs only when you click.`
    : "Select a classification target on the Target tab first.";
  $("sample-holdout").hidden = state.sample !== "customer_churn.csv";
}

async function runLabelReview() {
  if (state.busy) return;
  const out = clear($("label-review-results"));
  put(out, h("p", { class: "small muted", text: "Training cross-validated model…" }));
  setDashboardBusy(true);
  try {
    const res = await (await post("/api/label-review", baseForm())).json();
    clear(out);
    if (res.status === "unsupported") {
      put(out, h("div", { class: "alert alert-warn", text: res.reason }));
      return;
    }
    put(out,
      h("div", { class: "kv-grid" },
        kv("Rows used", fmtInt(res.n_rows_used)),
        kv("Out-of-fold accuracy", fmtPct(res.oof_accuracy)),
        kv("Balanced accuracy", fmtPct(res.oof_balanced_accuracy)),
        kv("Majority baseline", fmtPct(res.majority_baseline_accuracy)),
        kv("Disagreements", fmtInt(res.n_disagreements))),
      res.oof_balanced_accuracy !== null && res.oof_balanced_accuracy < 0.7
        ? h("div", { class: "alert alert-warn", text: "The model's balanced accuracy is low, so its disagreements carry little information about label quality." })
        : null,
      h("p", { class: "small muted", text: `${res.model}; ${res.cv_folds}-fold stratified CV, seed ${res.random_seed}. Features used: ${res.features_used.join(", ") || "none"}.` }),
      res.excluded_features.length
        ? h("p", { class: "small muted", text: `Excluded: ${res.excluded_features.map((e) => `${e.column} (${e.reason})`).join("; ")}.` })
        : null);
    if (res.candidates.length) {
      put(out, h("div", { class: "section-label", text: `Rows to review${res.candidates_truncated ? ` (first ${res.candidates.length})` : ""}` }),
        h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
          h("thead", {}, h("tr", {}, h("th", { class: "num", text: "Row" }), h("th", { text: "Given label" }),
            h("th", { text: "Model prefers" }), h("th", { class: "num", text: "P(given)" }), h("th", { class: "num", text: "P(preferred)" }))),
          h("tbody", {}, res.candidates.map((c) => h("tr", {},
            h("td", { class: "num", text: String(c.row_index) }), h("td", { text: c.given_label }),
            h("td", { text: c.predicted_label }), h("td", { class: "num", text: c.given_label_probability.toFixed(3) }),
            h("td", { class: "num", text: c.predicted_label_probability.toFixed(3) })))))));
    } else {
      put(out, h("p", { class: "small", text: "The model agrees with every label." }));
    }
    put(out, h("ul", { class: "small muted" }, res.limitations.map((l) => h("li", { text: l }))));
  } catch (err) {
    put(clear(out), h("div", { class: "alert alert-error", text: err.message }));
  } finally {
    setDashboardBusy(false);
  }
}

async function runOverlap(testFile) {
  if (state.busy) return;
  const out = clear($("overlap-results"));
  const problem = validateLocally(testFile);
  if (problem) {
    put(out, h("div", { class: "alert alert-error", text: problem }));
    return;
  }
  put(out, h("p", { class: "small muted", text: `Comparing with ${testFile.name}…` }));
  const form = new FormData();
  form.append("train_file", state.file, state.file.name);
  form.append("test_file", testFile, testFile.name);
  const target = state.result.settings.target_column;
  if (target) form.append("target_column", target);
  setDashboardBusy(true);
  try {
    const res = await (await post("/api/train-test-overlap", form)).json();
    put(clear(out),
      h("p", { class: "small muted", text: `${res.test.filename}: ${fmtInt(res.test.n_rows)} rows, ${res.common_columns.length} shared columns.` }),
      h("div", { class: "kv-grid" },
        kv("Test rows found in train", `${fmtInt(res.n_test_rows_in_train)} (${fmtPct(res.test_rows_in_train_fraction)})`),
        kv("Feature matches", res.n_test_feature_matches === null ? "needs target" : fmtInt(res.n_test_feature_matches)),
        kv("…with a different label", res.n_feature_matches_with_different_label === null ? "needs target" : fmtInt(res.n_feature_matches_with_different_label))),
      res.findings.length
        ? h("div", { class: "findings-list" }, res.findings.map((f, i) => findingCard(f, `overlap-${i}`)))
        : h("p", { class: "small", text: "No exact overlap found." }),
      h("ul", { class: "small muted" }, res.limitations.map((l) => h("li", { text: l }))));
  } catch (err) {
    put(clear(out), h("div", { class: "alert alert-error", text: err.message }));
  } finally {
    setDashboardBusy(false);
    $("test-file-input").value = "";
  }
}

// --- Corrections ---------------------------------------------------------------------------

function renderCorrections(r) {
  const root = clear($("corrections-content"));
  if (!r.corrections.length) {
    put(root, emptyState("No automatic corrections are proposed for this dataset. Missing values are not imputed here: imputation should be fitted on training data inside your modeling pipeline."));
    return;
  }
  const selected = new Map(); // id -> Set of columns (or true)
  const apply = h("button", { type: "button", class: "btn btn-primary", disabled: true }, "Apply to a copy");
  const approval = h("input", { type: "checkbox", id: "approve-corrections" });
  const result = h("div");
  const update = () => { apply.disabled = !(approval.checked && selected.size) || state.busy; };

  const items = r.corrections.map((c) => {
    const box = h("input", { type: "checkbox", id: `corr-${c.id}` });
    const columnBoxes = c.operation === "drop_columns"
      ? c.columns.map((name) => {
        const cb = h("input", { type: "checkbox", checked: true, "data-column": name });
        cb.addEventListener("change", () => {
          const set = selected.get(c.id);
          if (set) { if (cb.checked) set.add(name); else set.delete(name); if (!set.size) { selected.delete(c.id); box.checked = false; } }
          update();
        });
        return h("label", { class: "checkbox-inline" }, cb, h("code", { text: name }));
      })
      : [];
    box.addEventListener("change", () => {
      if (box.checked) {
        const cols = columnBoxes.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.dataset.column);
        selected.set(c.id, new Set(c.operation === "drop_columns" ? cols : []));
      } else {
        selected.delete(c.id);
      }
      update();
    });
    return h("div", { class: "correction" },
      h("label", { class: "correction-head", for: `corr-${c.id}` }, box,
        h("span", {}, h("strong", { text: c.title }),
          h("p", { text: c.description }),
          h("p", { class: "implications", text: `Implications: ${c.implications}` }))),
      columnBoxes.length ? h("div", { class: "column-choices" }, columnBoxes) : null);
  });
  approval.addEventListener("change", update);

  apply.addEventListener("click", async () => {
    const steps = r.corrections.filter((c) => selected.has(c.id)).map((c) => ({
      operation: c.operation,
      columns: c.operation === "drop_columns" ? [...selected.get(c.id)] : [],
    }));
    const plan = { approved: approval.checked, target_column: r.settings.target_column, steps };
    setDashboardBusy(true);
    apply.disabled = true;
    put(clear(result), h("p", { class: "small muted", text: "Applying corrections to a copy…" }));
    try {
      const res = await (await post("/api/corrections/apply", baseForm({ plan: JSON.stringify(plan) }))).json();
      renderCorrectionResult(result, res);
    } catch (err) {
      put(clear(result), h("div", { class: "alert alert-error", text: err.message }));
    } finally {
      setDashboardBusy(false);
      update();
    }
  });

  put(root,
    h("p", { class: "small muted", text: "Nothing is changed unless you select corrections, confirm, and apply. The original file is never modified; you receive a corrected copy and an audit record." }),
    ...items,
    h("label", { class: "approval", for: "approve-corrections" }, approval,
      h("span", {}, "I have reviewed the selected changes and their implications, and approve applying them to a copy of this dataset.")),
    apply, result);
}

function renderCorrectionResult(container, res) {
  const a = res.audit;
  const csvBlob = new Blob([res.csv], { type: "text/csv;charset=utf-8" });
  const auditBlob = new Blob([JSON.stringify(a, null, 2)], { type: "application/json" });
  put(clear(container), h("div", { class: "card", style: null },
    h("h2", { class: "card-title", text: "Corrected copy ready" }),
    h("p", { class: "small", text: `${fmtInt(a.input.n_rows)} → ${fmtInt(a.output.n_rows)} rows, ${fmtInt(a.input.n_columns)} → ${fmtInt(a.output.n_columns)} columns.` }),
    h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
      h("thead", {}, h("tr", {}, h("th", { text: "Step" }), h("th", { text: "Columns" }), h("th", { class: "num", text: "Rows" }), h("th", { class: "num", text: "Columns" }))),
      h("tbody", {}, a.steps.map((s) => h("tr", {},
        h("td", { text: label(s.operation) }), h("td", {}, s.columns.map((c) => h("span", { class: "chip", text: c }))),
        h("td", { class: "num", text: `${fmtInt(s.rows_before)} → ${fmtInt(s.rows_after)}` }),
        h("td", { class: "num", text: `${s.columns_before} → ${s.columns_after}` })))))),
    h("ul", { class: "small muted" }, a.notes.map((n) => h("li", { text: n }))),
    h("div", { class: "toolbar" },
      h("button", { type: "button", class: "btn btn-primary", onclick: () => downloadBlob(csvBlob, res.filename) }, "Download corrected CSV"),
      h("button", { type: "button", class: "btn", onclick: () => downloadBlob(auditBlob, res.filename.replace(/\.csv$/, ".audit.json")) }, "Download audit record"),
      h("button", {
        type: "button", class: "btn",
        onclick: () => startCorrectedAnalysis(new File([csvBlob], res.filename, { type: "text/csv" })),
      }, "Analyze corrected copy"))));
  container.firstChild.style.marginTop = "16px";
}

async function startCorrectedAnalysis(file) {
  const target = state.result.settings.target_column;
  setDashboardBusy(true);
  const form = new FormData();
  form.append("file", file, file.name);
  if (target) form.append("target_column", target);
  try {
    const result = await (await post("/api/analyze", form)).json();
    state.file = file;
    state.sample = null;
    state.selectedColumn = null;
    showDashboard(result);
    toast("Showing the analysis of the corrected copy.");
  } catch (err) {
    toast(err.message);
  } finally {
    setDashboardBusy(false);
  }
}

// --- Reports -------------------------------------------------------------------------------

async function downloadReport(format) {
  if (state.busy) return;
  setDashboardBusy(true);
  try {
    const form = baseForm({ format, include_values: $("include-values").checked ? "true" : "false" });
    const response = await post("/api/report", form);
    const stem = state.result.dataset.filename.replace(/\.csv$/i, "");
    downloadBlob(await response.blob(), filenameFrom(response, `datasentry-report-${stem}.${format}`));
  } catch (err) {
    toast(err.message);
  } finally {
    setDashboardBusy(false);
  }
}

// --- Tabs ----------------------------------------------------------------------------------

function selectTab(id) {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  for (const tab of tabs) {
    const active = tab.id === id;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    $(tab.getAttribute("aria-controls")).hidden = !active;
  }
}

function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => selectTab(tab.id));
    tab.addEventListener("keydown", (e) => {
      const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!delta) return;
      const next = tabs[(i + delta + tabs.length) % tabs.length];
      selectTab(next.id);
      next.focus();
    });
  });
}

// --- Theme ---------------------------------------------------------------------------------

const THEME_KEY = "datasentry-theme";

function applyTheme(choice) {
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  const input = document.querySelector(`.theme-input[value="${choice}"]`);
  if (input) input.checked = true;
}

function saveTheme(choice) {
  try {
    if (choice === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Not persisted when storage is unavailable; the choice still applies for this visit.
  }
}

function setupThemeSwitch() {
  applyTheme(document.documentElement.dataset.theme || "system"); // theme.js already applied it
  // Native radios handle clicks and arrow keys; persist whatever the user picks.
  document.querySelectorAll(".theme-input").forEach((input) => {
    input.addEventListener("change", () => {
      if (!input.checked) return;
      applyTheme(input.value);
      saveTheme(input.value);
    });
  });
}

// --- Startup -------------------------------------------------------------------------------

function setupUpload() {
  const zone = $("dropzone");
  const input = $("file-input");
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => { if (input.files[0]) startAnalysis(input.files[0]); });
  for (const type of ["dragenter", "dragover"]) {
    zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add("is-dragover"); });
  }
  for (const type of ["dragleave", "drop"]) {
    zone.addEventListener(type, () => zone.classList.remove("is-dragover"));
  }
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    const files = e.dataTransfer?.files;
    if (files && files.length > 1) {
      showUploadError(new ApiError("Drop one CSV file at a time."));
      return;
    }
    if (files && files[0]) startAnalysis(files[0]);
  });
  // Dropping a file outside the zone should not navigate away from the app.
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  document.querySelectorAll("[data-sample]").forEach((button) => {
    button.addEventListener("click", () => loadSample(button.dataset.sample, button.dataset.target));
  });
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const body = await response.json();
    state.limits = body.limits;
    $("api-status").textContent = `Local server · v${body.version}`;
    $("api-status").dataset.state = "ok";
    $("upload-hint").textContent =
      `UTF-8 CSV with a header row · up to ${fmtBytes(body.limits.max_upload_bytes)}, ` +
      `${fmtInt(body.limits.max_rows)} rows and ${fmtInt(body.limits.max_columns)} columns.`;
  } catch {
    $("api-status").textContent = "Server unreachable";
    $("api-status").dataset.state = "down";
  }
}

function init() {
  setupThemeSwitch();
  setupUpload();
  setupTabs();
  $("new-analysis").addEventListener("click", resetToUpload);
  $("download-json").addEventListener("click", () => downloadReport("json"));
  $("download-html").addEventListener("click", () => downloadReport("html"));
  for (const id of ["finding-search", "filter-severity", "filter-category", "filter-kind", "sort-findings"]) {
    $(id).addEventListener(id === "finding-search" ? "input" : "change", renderFindings);
  }
  $("column-search").addEventListener("input", renderColumns);
  $("filter-type").addEventListener("change", renderColumns);
  $("run-target").addEventListener("click", () => rerun($("target-select").value || null));
  $("run-label-review").addEventListener("click", runLabelReview);
  $("test-file-input").addEventListener("change", (e) => { if (e.target.files[0]) runOverlap(e.target.files[0]); });
  $("sample-holdout").addEventListener("click", async () => {
    try {
      const response = await fetch("/samples/customer_churn_holdout.csv");
      if (!response.ok) throw new Error();
      runOverlap(new File([await response.blob()], "customer_churn_holdout.csv", { type: "text/csv" }));
    } catch {
      toast("The sample holdout file could not be loaded.");
    }
  });
  loadHealth();
}

document.addEventListener("DOMContentLoaded", init);
