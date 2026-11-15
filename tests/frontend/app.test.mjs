// Unit tests for the pure helpers in frontend/app.js. Run: node --test tests/frontend/
// app.js is a classic browser script, so it is evaluated in a vm context with a fake DOM; its
// top-level declarations are then read from that context. No dependencies.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { Node, Text, Element, createDocument } from "./fake-dom.mjs";

const APP_JS = new URL("../../frontend/app.js", import.meta.url);

function loadApp() {
  const document = createDocument();
  const context = vm.createContext({
    document,
    Node,
    window: { addEventListener() {}, scrollTo() {} },
    console,
    setTimeout,
    clearTimeout,
  });
  vm.runInContext(readFileSync(APP_JS, "utf8"), context, { filename: "app.js" });
  // Top-level const/let live in the script's global lexical scope, so read them by evaluation.
  const get = (name) => vm.runInContext(name, context);
  return { document, get };
}

const { document, get } = loadApp();
const put = get("put");
const h = get("h");

const textNodes = (root) => [...root.descendants()].filter((n) => n instanceof Text);
const strayNulls = (root) => textNodes(root).filter((n) => /\b(null|undefined)\b/.test(n.data));

// --- put() ----------------------------------------------------------------------------------

test("put skips null, undefined and false instead of inserting them as text", () => {
  const el = put(new Element("div"), "a", null, undefined, false, "b");
  assert.equal(el.textContent, "ab");
  assert.equal(strayNulls(el).length, 0);
});

test("put keeps falsy values that are real content", () => {
  const el = put(new Element("div"), 0, "", "x");
  assert.equal(el.textContent, "0x");
});

test("put flattens nested arrays, as h() children do", () => {
  const el = put(new Element("ul"), [h("li", { text: "1" }), [h("li", { text: "2" }), [null, h("li", { text: "3" })]]]);
  assert.deepEqual(el.children.map((li) => li.textContent), ["1", "2", "3"]);
});

test("put inserts strings as text nodes, never as markup", () => {
  const el = put(new Element("div"), "<img src=x onerror=alert(1)>");
  assert.equal(el.children.length, 0);
  assert.equal(el.textContent, "<img src=x onerror=alert(1)>");
});

test("put returns its parent and preserves child order", () => {
  const parent = new Element("div");
  const a = new Element("span");
  assert.equal(put(parent, a, "t"), parent);
  assert.equal(parent.childNodes[0], a);
  assert.equal(parent.childNodes[1].textContent, "t");
});

// --- h() ------------------------------------------------------------------------------------

test("h maps class, text and attributes, and skips empty props", () => {
  const el = h("button", { class: "btn", text: "Go", type: "button", disabled: true, title: null, hidden: false });
  assert.equal(el.tagName, "BUTTON");
  assert.equal(el.className, "btn");
  assert.equal(el.textContent, "Go");
  assert.equal(el.getAttribute("type"), "button");
  assert.equal(el.getAttribute("disabled"), "");
  assert.equal(el.getAttribute("title"), null);
  assert.equal(el.getAttribute("hidden"), null);
});

test("h registers on* props as event listeners, not attributes", () => {
  let clicks = 0;
  const el = h("button", { onclick: () => { clicks += 1; } });
  assert.equal(el.getAttribute("onclick"), null);
  el.dispatch("click");
  assert.equal(clicks, 1);
});

test("h skips null children, the source of the old \"null\" text bug", () => {
  const el = h("p", {}, "a", null, h("b", { text: "b" }), undefined, false);
  assert.equal(el.textContent, "ab");
  assert.equal(strayNulls(el).length, 0);
});

test("h text prop is inserted literally", () => {
  const el = h("span", { text: "<script>alert(1)</script>" });
  assert.equal(el.children.length, 0);
  assert.equal(el.textContent, "<script>alert(1)</script>");
});

// --- Formatters -----------------------------------------------------------------------------

test("label turns snake_case keys into words", () => {
  assert.equal(get("label")("likely_issue"), "likely issue");
  assert.equal(get("label")("a_b_c"), "a b c");
});

test("missing values format as an em dash, never as null or NaN", () => {
  for (const name of ["fmtInt", "fmtPct", "fmtNum"]) {
    assert.equal(get(name)(null), "—", name);
    assert.equal(get(name)(undefined), "—", name);
  }
});

test("fmtInt and fmtNum use locale grouping for integers", () => {
  const expected = vm.runInContext("(1234567).toLocaleString()", vm.createContext({}));
  assert.equal(get("fmtInt")(1234567), expected);
  assert.equal(get("fmtNum")(1234567), expected);
});

test("fmtPct scales fractions and respects the digit count", () => {
  const fmtPct = get("fmtPct");
  assert.equal(fmtPct(0.1234), "12.3%");
  assert.equal(fmtPct(0.1234, 2), "12.34%");
  assert.equal(fmtPct(0), "0.0%");
  assert.equal(fmtPct(1), "100.0%");
});

test("fmtNum switches to exponent notation for very large and very small values", () => {
  const fmtNum = get("fmtNum");
  assert.equal(fmtNum(12345678.9), "1.235e+7");
  assert.equal(fmtNum(0.0000123), "1.230e-5");
  assert.equal(fmtNum(-0.0000123), "-1.230e-5");
  assert.equal(fmtNum(0), "0");
  assert.equal(fmtNum(0.5), "0.5");
});

test("fmtBytes picks the unit at the 1024 boundaries", () => {
  const fmtBytes = get("fmtBytes");
  assert.equal(fmtBytes(0), "0 B");
  assert.equal(fmtBytes(1023), "1023 B");
  assert.equal(fmtBytes(1024), "1.0 KB");
  assert.equal(fmtBytes(1024 * 1024 - 1), "1024.0 KB");
  assert.equal(fmtBytes(1024 * 1024), "1.0 MB");
  assert.equal(fmtBytes(25 * 1024 * 1024), "25.0 MB");
});

test("bar clamps its fill to the 0–100% range", () => {
  const bar = get("bar");
  const width = (fraction) => bar(fraction).children[0].style.width;
  assert.equal(width(-0.5), "0%");
  assert.equal(width(0.25), "25%");
  assert.equal(width(3), "100%");
  assert.equal(bar(0.5, true).className, "bar warn");
  assert.equal(bar(0.5, false).className, "bar");
});

// --- API error handling ---------------------------------------------------------------------

test("errorFromResponse prefers the server's fixed-template message", () => {
  const err = get("errorFromResponse")(400, { message: "The file is empty.", error: "empty_file" });
  assert.equal(err.message, "The file is empty.");
  assert.equal(err.code, "empty_file");
  assert.equal(err.status, 400);
});

test("errorFromResponse falls back to generic messages without echoing the body", () => {
  const fromResponse = get("errorFromResponse");
  assert.equal(fromResponse(413, null).code, "file_too_large");
  assert.equal(fromResponse(500, { detail: "Traceback: secret" }).code, "internal_error");
  assert.doesNotMatch(fromResponse(500, { detail: "Traceback: secret" }).message, /secret/);
  assert.equal(fromResponse(404, "not json").message, "The request failed (HTTP 404).");
});

test("parseJson returns null for invalid JSON instead of throwing", () => {
  const parseJson = get("parseJson");
  assert.equal(parseJson("{bad"), null);
  assert.equal(parseJson(""), null);
  assert.equal(parseJson('{"a":1}').a, 1); // vm-realm object, so compare the value, not the prototype
});

// --- Rendering ------------------------------------------------------------------------------

const baseFinding = {
  code: "high_missing_rate",
  title: "Column <b>x</b> is mostly empty",
  explanation: "62% of values are missing.",
  why_it_matters: "Models may learn from the missingness pattern.",
  recommendation: "Check how the column was collected.",
  limitations: null,
  severity: "medium",
  kind: "potential_issue",
  category: "completeness",
  columns: [],
  evidence: {},
  correction: null,
};

test("findingCard renders optional fields that are null without any \"null\" text", () => {
  const card = get("findingCard")(baseFinding, "f0");
  assert.equal(strayNulls(card).length, 0);
  assert.match(card.textContent, /Whole dataset/);
  assert.doesNotMatch(card.textContent, /Limitations/);
});

test("findingCard renders dataset-derived text literally and formats numeric evidence", () => {
  const card = get("findingCard")({
    ...baseFinding,
    limitations: "Based on a sample.",
    evidence: { missing_fraction: 0.62, note: "<i>raw</i>" },
  }, "f1");
  assert.ok(textNodes(card).some((n) => n.data === "Column <b>x</b> is mostly empty"));
  assert.ok(textNodes(card).some((n) => n.data === "<i>raw</i>"));
  assert.ok(textNodes(card).some((n) => n.data === "0.62"));
  assert.match(card.textContent, /Limitations/);
});

test("findingCard toggles aria-expanded and the body's hidden state", () => {
  const card = get("findingCard")(baseFinding, "f2");
  const [head, body] = card.children;
  assert.equal(head.getAttribute("aria-expanded"), "false");
  assert.equal(head.getAttribute("aria-controls"), "f2-body");
  head.dispatch("click");
  assert.equal(head.getAttribute("aria-expanded"), "true");
  assert.equal(body.hidden, false);
  head.dispatch("click");
  assert.equal(body.hidden, true);
});

test("rangePlot returns nothing for degenerate ranges", () => {
  const rangePlot = get("rangePlot");
  assert.equal(rangePlot({ min: null, max: 3 }), null);
  assert.equal(rangePlot({ min: 2, max: 2, q1: 2, q3: 2, median: 2 }), null);
  const plot = rangePlot({ min: 0, max: 10, q1: 2, q3: 8, median: 5 });
  assert.equal(strayNulls(plot).length, 0);
});

assert.ok(document, "fake document is wired into the app context");

// --- Review decisions (import validation) -------------------------------------------------------

const goodReview = { finding_code: "constant_column", columns: ["country"], status: "accepted_risk", note: "known", decided_at: "2026-01-02T03:04:05Z" };

test("validReviews keeps well-formed decisions and copies only known fields", () => {
  const out = get("validReviews")([{ ...goodReview, extra: "<script>" }]);
  assert.equal(out.length, 1);
  assert.deepEqual(Object.keys(out[0]).sort(), ["columns", "decided_at", "finding_code", "note", "status"]);
  assert.equal(out[0].note, "known");
});

test("validReviews drops malformed decisions from untrusted files", () => {
  const validReviews = get("validReviews");
  const bad = [
    { ...goodReview, status: "approved" },
    { ...goodReview, note: "n".repeat(281) },
    { ...goodReview, columns: [1] },
    { ...goodReview, finding_code: "" },
    { ...goodReview, decided_at: 5 },
    null, "text", 42,
  ];
  assert.equal(validReviews(bad).length, 0);
  assert.equal(validReviews({ reviews: [goodReview] }).length, 0); // not a list
  assert.equal(validReviews(undefined).length, 0);
});

test("review keys distinguish columns", () => {
  const reviewKey = get("reviewKey");
  assert.notEqual(reviewKey("constant_column", ["a"]), reviewKey("constant_column", ["b"]));
  assert.equal(reviewKey("x", ["a", "b"]), reviewKey("x", ["a", "b"]));
});
