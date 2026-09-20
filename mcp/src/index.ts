#!/usr/bin/env node
/**
 * bullwhip MCP server — stdio transport, six read-only tools.
 *
 * Makes bullwhip legible to Claude/agents without exposing a shell.
 * The agent client (Claude Desktop, etc.) spawns this on demand.
 *
 * Tools:
 *   night_status(date?)          — attempt N/23, heartbeat, scheduler alive?
 *   night_stats(date?)           — data-layer runs, record counts, table rows
 *   list_targets(date?)          — per-target state + durations
 *   night_summary(date?)         — digest: counts, runtime, failures, critical path
 *   get_target_log(target, date?) — raw or tail N lines of a target's log
 *   explain_critical_path(date?) — why the night is ordered the way it is
 *
 * Write tools (run_target, reset_marker) are default-off, allowlisted, never nuke.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { readFileSync, existsSync, readdirSync, statSync } from "fs";
import { join, resolve } from "path";
import {
  parseTimingLog,
  reduceToTargets,
  getSummary,
  type StatusJson,
  type DagJson,
  type TargetState,
} from "../core/parsers.js";

interface LedgerJson {
  generated_at: string;
  since: string;
  runs: Record<string, unknown>[];
  records_extracted: number;
  records_loaded: number;
  tables: Record<string, number>;
  errors: string[];
}

// Resolve the project root from BULLWHIP_PROJECT_DIR or cwd.
const PROJECT_ROOT = process.env.BULLWHIP_PROJECT_DIR || process.cwd();

function todayStr(): string {
  const date = new Date();
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function getLogDir(date?: string): string {
  return join(PROJECT_ROOT, "logs", date || todayStr());
}

function readJsonFile<T>(path: string): T | null {
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, "utf-8")) as T;
  } catch {
    return null;
  }
}

function readTextFile(path: string): string | null {
  if (!existsSync(path)) return null;
  return readFileSync(path, "utf-8");
}

// --- Tool implementations ---

function nightStatus(date?: string): string {
  const logDir = getLogDir(date);
  const status = readJsonFile<StatusJson>(join(logDir, "status.json"));

  if (!status) {
    return JSON.stringify({ error: "No status.json found. The scheduler may not have run yet." });
  }

  let heartbeatAge: number | null = null;
  if (status.heartbeat) {
    heartbeatAge = (Date.now() - new Date(status.heartbeat).getTime()) / 1000;
  }

  return JSON.stringify({
    date: date || todayStr(),
    ...status,
    heartbeat_age_seconds: heartbeatAge !== null ? Math.round(heartbeatAge) : null,
    scheduler_alive: heartbeatAge !== null ? heartbeatAge < 90 : null,
  }, null, 2);
}

function nightStats(date?: string): string {
  const ledger = readJsonFile<LedgerJson>(join(getLogDir(date), "ledger.json"));

  if (!ledger) {
    return JSON.stringify({ error: "No ledger.json found. Data-layer stats may not have been generated yet." });
  }

  return JSON.stringify({
    date: date || todayStr(),
    ...ledger,
  }, null, 2);
}

function listTargets(date?: string): string {
  const logDir = getLogDir(date);
  const timingText = readTextFile(join(logDir, "timing_env.log"));
  if (!timingText) {
    return JSON.stringify({ error: "No timing_env.log found for this date." });
  }

  const records = parseTimingLog(timingText);
  const targets = reduceToTargets(records);
  const summary = getSummary(targets);

  return JSON.stringify({
    summary,
    targets: targets.map((t) => ({
      target: t.target,
      status: t.status,
      duration_seconds: Math.round(t.duration * 10) / 10,
      exit_code: t.exit_code,
      started_at: t.started_at.toISOString(),
      finished_at: t.finished_at?.toISOString(),
    })),
  }, null, 2);
}

function nightSummary(date?: string): string {
  const logDir = getLogDir(date);
  const timingText = readTextFile(join(logDir, "timing_env.log"));
  const status = readJsonFile<StatusJson>(join(logDir, "status.json"));
  const ledger = readJsonFile<LedgerJson>(join(logDir, "ledger.json"));
  const dag = readJsonFile<DagJson>(join(logDir, "dag.json"));

  if (!timingText) {
    return JSON.stringify({ error: "No timing_env.log found for this date." });
  }

  const records = parseTimingLog(timingText);
  const targets = reduceToTargets(records);
  const summary = getSummary(targets);

  const failed = targets.filter((t) => t.status === "failed");
  const slowest = [...targets].sort((a, b) => b.duration - a.duration).slice(0, 5);

  let criticalPath = "";
  if (dag) {
    const sorted = [...dag.targets].sort(
      (a, b) => b.longest_downstream - a.longest_downstream
    );
    const top = sorted.slice(0, 5);
    criticalPath = top
      .map((t) => `  ${t.id}: ${t.longest_downstream.toFixed(1)}s (avg ${t.avg_duration.toFixed(1)}s)`)
      .join("\n");
  }

  return JSON.stringify({
    date: date || todayStr(),
    status: status?.status || "unknown",
    succeeded: summary.succeeded,
    failed: summary.failed,
    running: summary.running,
    total_runtime_seconds: Math.round(summary.totalDuration),
    records_extracted: ledger?.records_extracted ?? null,
    records_loaded: ledger?.records_loaded ?? null,
    tables: ledger?.tables ?? {},
    data_errors: ledger?.errors ?? [],
    failed_targets: failed.map((t) => ({
      target: t.target,
      exit_code: t.exit_code,
      duration: Math.round(t.duration * 10) / 10,
    })),
    slowest_targets: slowest.map((t) => ({
      target: t.target,
      duration: Math.round(t.duration * 10) / 10,
    })),
    critical_path: criticalPath || "No dag.json available. Run critical_path.py to generate.",
  }, null, 2);
}

function getTargetLog(target: string, date?: string, lines?: number): string {
  const logDir = getLogDir(date);
  const safeName = target.replace(/\//g, "_");
  const logPath = join(logDir, `${safeName}.log`);
  const content = readTextFile(logPath);

  if (!content) {
    return JSON.stringify({ error: `No log found for target '${target}' on ${date || todayStr()}.` });
  }

  if (lines && lines > 0) {
    const allLines = content.split("\n");
    const tail = allLines.slice(-lines).join("\n");
    return tail;
  }

  return content;
}

function explainCriticalPath(date?: string): string {
  const dag = readJsonFile<DagJson>(join(getLogDir(date), "dag.json"));

  if (!dag) {
    return JSON.stringify({
      error: "No dag.json found. Run `python lib/critical_path.py` to generate it.",
    });
  }

  const sorted = [...dag.targets].sort(
    (a, b) => b.longest_downstream - a.longest_downstream
  );

  const waves = new Map<number, string[]>();
  for (const t of dag.targets) {
    if (!waves.has(t.depth)) waves.set(t.depth, []);
    waves.get(t.depth)!.push(t.id);
  }

  const waveDescriptions = [...waves.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([depth, targets]) => {
      return `Wave ${depth}: ${targets.join(", ")}`;
    });

  return JSON.stringify({
    total_targets: dag.targets.length,
    total_waves: waves.size,
    critical_path_top_5: sorted
      .slice(0, 5)
      .map((t) => `${t.id}: ${t.longest_downstream.toFixed(1)}s downstream`),
    waves: waveDescriptions,
    generated_at: dag.generated_at,
  }, null, 2);
}

// --- Server setup ---

const server = new Server(
  { name: "bullwhip", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "night_status",
      description: "Get scheduler status from status.json, plus derived heartbeat age and liveness.",
      inputSchema: {
        type: "object",
        properties: {
          date: { type: "string", description: "Date (YYYY-MM-DD). Defaults to today." },
        },
      },
    },
    {
      name: "night_stats",
      description: "Get data-layer stats from ledger.json: runs, extracted/loaded records, table row counts, and errors.",
      inputSchema: {
        type: "object",
        properties: {
          date: { type: "string", description: "Date (YYYY-MM-DD). Defaults to today." },
        },
      },
    },
    {
      name: "list_targets",
      description: "List all make targets and their execution state (running/succeeded/failed) with durations.",
      inputSchema: {
        type: "object",
        properties: {
          date: { type: "string", description: "Date (YYYY-MM-DD). Defaults to today." },
        },
      },
    },
    {
      name: "night_summary",
      description: "Get a digest of the night: counts, total runtime, failed targets, slowest targets, critical path.",
      inputSchema: {
        type: "object",
        properties: {
          date: { type: "string", description: "Date (YYYY-MM-DD). Defaults to today." },
        },
      },
    },
    {
      name: "get_target_log",
      description: "Read the raw log of a specific make target. Optionally tail the last N lines.",
      inputSchema: {
        type: "object",
        properties: {
          target: { type: "string", description: "The make target name." },
          date: { type: "string", description: "Date (YYYY-MM-DD). Defaults to today." },
          lines: { type: "number", description: "Number of lines to tail (0 = full log)." },
        },
        required: ["target"],
      },
    },
    {
      name: "explain_critical_path",
      description: "Explain why the night is ordered the way it is: critical path, depth waves, longest downstream.",
      inputSchema: {
        type: "object",
        properties: {
          date: { type: "string", description: "Date (YYYY-MM-DD). Defaults to today." },
        },
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const date = (args as any)?.date as string | undefined;

  let result: string;

  switch (name) {
    case "night_status":
      result = nightStatus(date);
      break;
    case "night_stats":
      result = nightStats(date);
      break;
    case "list_targets":
      result = listTargets(date);
      break;
    case "night_summary":
      result = nightSummary(date);
      break;
    case "get_target_log":
      result = getTargetLog(
        (args as any).target as string,
        date,
        (args as any)?.lines as number | undefined
      );
      break;
    case "explain_critical_path":
      result = explainCriticalPath(date);
      break;
    default:
      result = JSON.stringify({ error: `Unknown tool: ${name}` });
  }

  return {
    content: [{ type: "text", text: result }],
  };
});

// Start the server.
const transport = new StdioServerTransport();
server.connect(transport).then(() => {
  console.error("[bullwhip-mcp] Server started on stdio");
});
