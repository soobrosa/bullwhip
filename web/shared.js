// shared.js — loads one night's artifacts and derives a single view model.
//
// Every dashboard (a/b/c/d.html) imports this and only differs in rendering.
// Inputs, all written by pipeline/lib/ during the night, served by plain http.server
// from the repo root:
//   <project>/logs/<date>/status.json      run_workflow.sh heartbeat
//   <project>/logs/<date>/timing_env.log   tracking_shell BEGIN/END records
//   <project>/logs/<date>/ledger.json      run_ledger.py (dlt-ops runs, row counts)
//   <project>/logs/<date>/dag.json         critical_path.py
//   <project>/logs/<date>/<target>.log     per-target stdout/stderr
//   <project>/logs/<date>/attempt-NN.log   make's own output per attempt

export function params() {
  const q = new URLSearchParams(location.search);
  const project = (q.get("project") || ".").replace(/\/+$/, "");
  const date = q.get("date") || localToday();
  return { project, date, dateExplicit: q.has("date") };
}

export function localToday() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Relative to web/, not the origin root, so the same files work from
// `python3 -m http.server` at the repo root and from GitHub Pages under
// /<repo>/web/.
export function logsRoot({ project }) {
  return `../${project}/logs/`;
}

export function logBase(p) {
  return `${logsRoot(p)}${p.date}/`;
}

async function fetchText(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) return null;
  return r.text();
}

async function fetchJSON(url) {
  const t = await fetchText(url);
  if (t == null) return null;
  try { return JSON.parse(t); } catch { return null; }
}

// run_workflow.sh writes logs/index.json after every night; static hosts have
// nothing else.  Locally, fall back to parsing http.server's HTML directory
// listing so nights from before the index existed still show.  Best effort.
export async function listNights(p) {
  const root = logsRoot(p);
  const idx = await fetchJSON(root + "index.json");
  if (Array.isArray(idx) && idx.length) return [...idx].sort().reverse();
  const html = await fetchText(root);
  if (!html) return [];
  const re = /href="(\d{4}-\d{2}-\d{2})\/"/g;
  const out = [];
  let m;
  while ((m = re.exec(html))) out.push(m[1]);
  return out.sort().reverse();
}

export const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;
export const stripAnsi = (s) => (s || "").replace(ANSI_RE, "");

// "intermediate/2026-09-09/validate.done" -> "validate"; directory targets
// keep their last segment so the marker folder still has a name.
export function shortName(id) {
  if (!id) return "";
  const parts = id.split("/").filter(Boolean);
  const dateIdx = parts.findIndex((p) => /^\d{4}-\d{2}-\d{2}$/.test(p));
  let tail = dateIdx >= 0 ? parts.slice(dateIdx + 1) : parts;
  if (tail.length === 0) tail = [parts[dateIdx - 1] + "/"];
  return tail.join("/").replace(/\.done$/, "");
}

export function isHelper(cmd) {
  return /^\s*(touch|mkdir|rm|@?echo)\b/.test(cmd || "");
}

export function parseTiming(text) {
  const begins = new Map();
  const commands = [];
  for (const line of (text || "").split("\n")) {
    if (!line.trim()) continue;
    let rec;
    try { rec = JSON.parse(line); } catch { continue; }
    if (rec.tag === "BEGIN") {
      const c = {
        key: rec.unique_nr,
        target: rec.target,
        short: shortName(rec.target),
        command: rec.command,
        helper: isHelper(rec.command),
        started: new Date(rec.started_at),
        finished: null,
        exit: null,
        state: "running",
      };
      begins.set(rec.unique_nr, c);
      commands.push(c);
    } else if (rec.tag === "END") {
      const c = begins.get(rec.unique_nr);
      if (!c) continue;
      c.finished = new Date(rec.finished_at);
      c.exit = rec.exit_code;
      c.state = rec.exit_code === 0 ? "success" : "failed";
    }
  }
  commands.sort((a, b) => a.started - b.started);
  return commands;
}

export function groupTargets(commands, now) {
  const byId = new Map();
  for (const c of commands) {
    if (!byId.has(c.target)) {
      byId.set(c.target, {
        id: c.target, short: c.short, commands: [],
        started: c.started, finished: null, state: "success", exit: 0,
      });
    }
    const t = byId.get(c.target);
    t.commands.push(c);
    if (c.started < t.started) t.started = c.started;
    if (c.finished && (!t.finished || c.finished > t.finished)) t.finished = c.finished;
  }
  for (const t of byId.values()) {
    if (t.commands.some((c) => c.state === "running")) { t.state = "running"; t.exit = null; t.finished = null; }
    else if (t.commands.some((c) => c.state === "failed")) { t.state = "failed"; t.exit = t.commands.find((c) => c.state === "failed").exit; }
    t.duration = ((t.finished || now) - t.started) / 1000;
    t.logFile = t.id.replace(/\//g, "_") + ".log";
  }
  return [...byId.values()].sort((a, b) => a.started - b.started);
}

export function durationOf(c, now) {
  return ((c.finished || now) - c.started) / 1000;
}

export function nightState(status, commands) {
  if (!status) return "no-data";
  if (status.status === "finished") return "finished";
  const running = commands.some((c) => c.state === "running");
  if (status.make_exit === -1 || status.make_exit == null) return running ? "running" : "starting";
  if (status.make_exit === 0) return "success";
  return "failed";
}

export function stateLabel(state) {
  return {
    "no-data": "no data for this night",
    starting: "starting",
    running: "running",
    success: "succeeded",
    failed: "failed",
    finished: "finished",
  }[state] || state;
}

export function fmtSecs(s) {
  if (s == null || isNaN(s)) return "–";
  if (s < 10) return `${s.toFixed(2)}s`;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  if (m < 60) return `${m}m ${String(r).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function fmtTime(d) {
  if (!d) return "–";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function fmtInt(n) {
  return n == null ? "–" : Number(n).toLocaleString("en-US");
}

// Match dlt-ops ledger runs to the make target whose window contains them.
function attachLedgerRuns(targets, ledger) {
  for (const t of targets) t.ledgerRuns = [];
  for (const run of ledger?.runs || []) {
    const s = new Date(run.started_at);
    const host = targets.find((t) => s >= new Date(t.started - 2000) && (!t.finished || s <= t.finished));
    if (host) host.ledgerRuns.push(run);
  }
}

export async function loadNight(p = params()) {
  let base = logBase(p);
  let [status, timing, ledger, dag] = await Promise.all([
    fetchJSON(base + "status.json"),
    fetchText(base + "timing_env.log"),
    fetchJSON(base + "ledger.json"),
    fetchJSON(base + "dag.json"),
  ]);
  // No ?date= and nothing for the viewer's "today" (a published site is read
  // at any hour, from any timezone): show the most recent night instead.
  if (!p.dateExplicit && status == null && timing == null) {
    const [latest] = await listNights(p);
    if (latest && latest !== p.date) {
      p = { ...p, date: latest };
      base = logBase(p);
      [status, timing, ledger, dag] = await Promise.all([
        fetchJSON(base + "status.json"),
        fetchText(base + "timing_env.log"),
        fetchJSON(base + "ledger.json"),
        fetchJSON(base + "dag.json"),
      ]);
    }
  }
  const now = new Date();
  const commands = parseTiming(timing);
  const targets = groupTargets(commands, now);
  attachLedgerRuns(targets, ledger);
  const state = nightState(status, commands);

  const started = commands.length ? commands[0].started : (status?.started_at ? new Date(status.started_at) : null);
  const finishedCandidates = commands.filter((c) => c.finished).map((c) => c.finished);
  const finished = state === "running" || state === "starting"
    ? null
    : (finishedCandidates.length ? new Date(Math.max(...finishedCandidates)) : null);
  const end = finished || now;

  // dag.json carries only user targets; annotate with tonight's outcome.
  // make's database strips trailing slashes, so match "dir/" targets loosely.
  const norm = (s) => s.replace(/\/+$/, "");
  const dagTargets = (dag?.targets || []).map((t) => ({
    ...t,
    short: shortName(t.id),
    depsShort: t.deps.map(shortName),
    outcome: targets.find((x) => norm(x.id) === norm(t.id)) || null,
  }));
  const criticalPath = dagTargets.length
    ? dagTargets.reduce((a, b) => (b.longest_downstream > a.longest_downstream ? b : a))
    : null;

  let attemptLog = null;
  if (status?.attempt != null) {
    attemptLog = stripAnsi(await fetchText(base + `attempt-${String(status.attempt).padStart(2, "0")}.log`));
  }

  return {
    ...p, base, status, ledger, dag: dagTargets, criticalPath, commands, targets, state,
    started, finished, end, now,
    elapsed: started ? (end - started) / 1000 : null,
    failedTargets: targets.filter((t) => t.state === "failed"),
    runningTargets: targets.filter((t) => t.state === "running"),
    attemptLog,
    fetchTargetLog: async (t) => stripAnsi(await fetchText(base + t.logFile)),
  };
}

// Compute the path from the DAG's longest chain, walking down through deps.
export function criticalChain(dag) {
  if (!dag.length) return [];
  const byId = new Map(dag.map((t) => [t.id, t]));
  let cur = dag.reduce((a, b) => (b.longest_downstream > a.longest_downstream ? b : a));
  const chain = [cur];
  while (cur && cur.deps.length) {
    const next = cur.deps.map((d) => byId.get(d)).filter(Boolean)
      .reduce((a, b) => (!a || b.longest_downstream > a.longest_downstream ? b : a), null);
    if (!next || next.longest_downstream <= 0) break;
    chain.push(next);
    cur = next;
  }
  return chain.reverse();
}

// Re-render every few seconds while the night is still moving.
export function autoRefresh(render, everyMs = 3000) {
  let timer = null;
  const tick = async () => {
    const night = await loadNight();
    render(night);
    const live = night.state === "running" || night.state === "starting";
    document.title = `${night.state} · bullwhip ${night.date}`;
    timer = setTimeout(tick, live ? everyMs : everyMs * 10);
  };
  tick();
  return () => clearTimeout(timer);
}

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v != null) e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

export function nightPicker(current, onChange) {
  const sel = el("select", { onchange: (e) => onChange(e.target.value) });
  listNights(params()).then((nights) => {
    if (!nights.includes(current)) nights.unshift(current);
    for (const n of nights) sel.append(el("option", { value: n, selected: n === current ? "" : null }, n));
  });
  return sel;
}

export function gotoNight(date) {
  const q = new URLSearchParams(location.search);
  q.set("date", date);
  location.search = q.toString();
}
