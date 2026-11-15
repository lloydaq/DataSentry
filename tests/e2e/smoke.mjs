// End-to-end browser smoke test. Run from the repository root: node tests/e2e/smoke.mjs
//
// Starts the real app (uvicorn) on a free loopback port and drives headless Chrome through the
// DevTools protocol (no dependencies; needs Node >= 22 for the built-in WebSocket):
//   theme switch + persistence -> load a sample -> findings -> every tab -> label review ->
//   train/test overlap -> phone-width layout,
// failing on any CSP violation, uncaught exception, console error or stray "null" text.
//
// Environment: PYTHON (default: the repo venv, else "python"), CHROME_PATH (default: common
// install locations), SMOKE_TIMEOUT_MS (per wait, default 60000).
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..", "..");
const TIMEOUT = Number(process.env.SMOKE_TIMEOUT_MS || 60000);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function firstExisting(paths) {
  return paths.find((p) => p && existsSync(p));
}

const PYTHON = process.env.PYTHON || firstExisting([
  join(ROOT, ".venv", "Scripts", "python.exe"),
  join(ROOT, ".venv", "bin", "python"),
]) || "python";

const CHROME = firstExisting([
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
]);

function freePort() {
  return new Promise((res, rej) => {
    const srv = createServer();
    srv.once("error", rej);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => res(port));
    });
  });
}

async function waitFor(what, check) {
  const deadline = Date.now() + TIMEOUT;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await check();
      if (last) return last;
    } catch (err) {
      last = err;
    }
    await sleep(200);
  }
  throw new Error(`Timed out waiting for ${what}${last instanceof Error ? ` (${last.message})` : ""}`);
}

const failures = [];
function check(condition, message) {
  if (condition) console.log(`  ok   ${message}`);
  else { console.log(`  FAIL ${message}`); failures.push(message); }
}

async function main() {
  if (!CHROME) throw new Error("Chrome was not found; set CHROME_PATH.");
  const appPort = await freePort();
  const debugPort = await freePort();
  const base = `http://127.0.0.1:${appPort}`;
  const profile = mkdtempSync(join(tmpdir(), "datasentry-smoke-"));
  const children = [];

  try {
    const server = spawn(PYTHON, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(appPort)], {
      cwd: ROOT, stdio: ["ignore", "ignore", "pipe"],
    });
    children.push(server);
    let serverLog = "";
    server.stderr.on("data", (d) => { serverLog = (serverLog + d).slice(-4000); });
    server.on("exit", (code) => { if (code) console.error(`uvicorn exited with ${code}\n${serverLog}`); });
    await waitFor("the API to become healthy", async () => (await fetch(`${base}/api/health`)).ok);

    const chromeArgs = [
      "--headless=new", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`,
      "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank",
    ];
    if (process.env.CI) chromeArgs.unshift("--no-sandbox"); // CI containers lack the user namespace sandbox
    children.push(spawn(CHROME, chromeArgs, { stdio: "ignore" }));
    const targets = await waitFor("Chrome DevTools", async () => (await fetch(`http://127.0.0.1:${debugPort}/json`)).json());
    const page = targets.find((t) => t.type === "page");

    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((r, j) => { ws.addEventListener("open", r); ws.addEventListener("error", j); });
    let nextId = 0;
    const pending = new Map();
    const problems = [];
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
      if (msg.method === "Runtime.exceptionThrown") problems.push(`exception: ${msg.params.exceptionDetails.text}`);
      if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") problems.push("console.error call");
      if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
        const { source, text } = msg.params.entry;
        // A failed favicon fetch is browser noise, not an app error.
        if (!/favicon/i.test(text)) problems.push(`${source}: ${text}`);
      }
    });
    const send = (method, params = {}) => new Promise((res, rej) => {
      const id = ++nextId;
      pending.set(id, (m) => (m.error ? rej(new Error(`${method}: ${m.error.message}`)) : res(m.result)));
      ws.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async (expression) => {
      const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
      return r.result.value;
    };
    const navigate = async (url) => {
      await send("Page.navigate", { url });
      await waitFor("the app to load", () => evaluate(`document.getElementById("api-status")?.dataset.state === "ok"`));
    };

    await send("Page.enable");
    await send("Runtime.enable");
    await send("Log.enable");
    await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    // Runs before page scripts on every load; DevTools-injected scripts are not subject to the page CSP.
    await send("Page.addScriptToEvaluateOnNewDocument", {
      source: `window.__csp = []; document.addEventListener("securitypolicyviolation",
        (e) => window.__csp.push(e.violatedDirective + " " + e.blockedURI));`,
    });

    console.log("Theme");
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });
    await navigate(base + "/");
    check(await evaluate(`document.documentElement.dataset.theme === undefined`), "System is the default choice");
    await evaluate(`document.querySelector('.theme-input[value="dark"]').click()`);
    check(await evaluate(`document.documentElement.dataset.theme === "dark"`), "choosing Dark overrides a light OS");
    await navigate(base + "/");
    check(await evaluate(`document.documentElement.dataset.theme === "dark"
      && document.querySelector('.theme-input[value="dark"]').checked`), "Dark persists across a reload");
    await evaluate(`document.querySelector('.theme-input[value="system"]').click()`);
    check(await evaluate(`document.documentElement.dataset.theme === undefined
      && localStorage.getItem("datasentry-theme") === null`), "choosing System clears the saved choice");

    console.log("Analysis");
    await evaluate(`document.querySelector('[data-sample="customer_churn.csv"]').click()`);
    await waitFor("the dashboard", () => evaluate(`!document.getElementById("dashboard").hidden
      && document.querySelectorAll("#findings-list .finding").length > 0`));
    check(await evaluate(`document.getElementById("summary-status").textContent.trim().length > 0`), "summary status is shown");
    const findings = await evaluate(`document.querySelectorAll("#findings-list .finding").length`);
    check(findings > 0, `findings are listed (${findings})`);
    await evaluate(`document.querySelector("#findings-list .finding-head").click()`);
    check(await evaluate(`document.querySelector("#findings-list .finding-head").getAttribute("aria-expanded") === "true"
      && !document.querySelector("#findings-list .finding-body").hidden`), "a finding expands to show its evidence");

    const tabs = await evaluate(`[...document.querySelectorAll('[role="tab"]')].map((t) => t.id)`);
    for (const id of tabs) {
      await evaluate(`document.getElementById("${id}").click()`);
      const shown = await evaluate(`(() => {
        const panel = document.getElementById(document.getElementById("${id}").getAttribute("aria-controls"));
        return !panel.hidden && panel.textContent.trim().length > 0;
      })()`);
      check(shown, `tab ${id} shows its panel`);
    }

    console.log("ML checks");
    await evaluate(`document.getElementById("tab-ml").click(); document.getElementById("run-label-review").click()`);
    await waitFor("label review", () => evaluate(`(() => {
      const out = document.getElementById("label-review-results");
      return out.textContent.trim().length > 0 && !/Training cross-validated model/.test(out.textContent);
    })()`));
    check(await evaluate(`!document.querySelector("#label-review-results .alert-error")`), "label review completes without an error");
    await evaluate(`document.getElementById("sample-holdout").click()`);
    await waitFor("train/test overlap", () => evaluate(`document.getElementById("overlap-results").textContent.trim().length > 0
      && !/Comparing|Checking/.test(document.getElementById("overlap-results").textContent)`));
    check(await evaluate(`!document.querySelector("#overlap-results .alert-error")
      && /Test rows found in train/.test(document.getElementById("overlap-results").textContent)`), "train/test overlap shows its result");

    console.log("Review log");
    const note = "<b>known</b> & accepted";
    await evaluate(`(() => {
      document.getElementById("tab-findings").click();
      const card = document.querySelector("#findings-list .finding");
      const head = card.querySelector(".finding-head");
      if (head.getAttribute("aria-expanded") !== "true") head.click();
      card.querySelector(".review-editor select").value = "accepted_risk";
      card.querySelector(".review-note").value = ${JSON.stringify(note)};
      card.querySelector(".review-editor button").click();
      return true;
    })()`);
    check(await evaluate(`(() => {
      const tag = document.querySelector("#findings-list .finding .finding-review");
      return !tag.hidden && tag.textContent.includes("Accepted risk") && tag.textContent.includes(${JSON.stringify(note)})
        && !tag.querySelector("b");
    })()`), "a decision is saved and its note is shown as text");
    check(await evaluate(`/^1 of \\d+ findings reviewed$/.test(document.getElementById("review-count").textContent)`),
      "the review count updates");
    // Export through the report endpoint, exactly as the download buttons send it.
    const exported = await evaluate(`(async () => {
      const form = baseForm({ format: "json", include_values: "false" });
      form.set("reviews", JSON.stringify(currentReviews()));
      const doc = await (await fetch("/api/report", { method: "POST", body: form })).json();
      window.__exportedReport = doc;
      return doc.reviews.length === 1 && doc.reviews[0].status === "accepted_risk" && doc.reviews[0].note === ${JSON.stringify(note)};
    })()`);
    check(exported, "the exported JSON report carries the decision");
    // Forget everything in the tab, then import the exported report.
    await evaluate(`sessionStorage.clear(); state.reviews = new Map(); renderFindings(); true`);
    check(await evaluate(`document.querySelector("#findings-list .finding .finding-review").hidden`), "decisions can be cleared");
    await evaluate(`importReviews(new File([JSON.stringify(window.__exportedReport)], "report.json", { type: "application/json" }))`);
    check(await evaluate(`(() => {
      const tag = document.querySelector("#findings-list .finding .finding-review");
      return !tag.hidden && tag.textContent.includes("Accepted risk") && tag.textContent.includes(${JSON.stringify(note)});
    })()`), "importing the exported report restores the decision");

    console.log("Integrity");
    const nulls = await evaluate(`(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const found = [];
      while (walker.nextNode()) if (/^\\s*(null|undefined|NaN)\\s*$/.test(walker.currentNode.data)) found.push(walker.currentNode.parentElement?.className || "?");
      return found;
    })()`);
    check(nulls.length === 0, `no stray null/undefined/NaN text${nulls.length ? ` (in: ${nulls.join(", ")})` : ""}`);

    await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
    await sleep(300);
    check(await evaluate(`document.documentElement.scrollWidth <= window.innerWidth`), "no horizontal scroll at 375px");

    const csp = await evaluate(`window.__csp`);
    check(csp.length === 0, `no CSP violations${csp.length ? `: ${csp.join("; ")}` : ""}`);
    check(problems.length === 0, `no console errors or exceptions${problems.length ? `: ${problems.join("; ")}` : ""}`);
    ws.close();
  } finally {
    for (const child of children.reverse()) child.kill();
    await sleep(500);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may still hold files on Windows */ }
  }
}

main().then(
  () => {
    if (failures.length) { console.error(`\n${failures.length} check(s) failed.`); process.exit(1); }
    console.log("\nSmoke test passed.");
    process.exit(0);
  },
  (err) => { console.error(`\nSmoke test error: ${err.message}`); process.exit(1); },
);
