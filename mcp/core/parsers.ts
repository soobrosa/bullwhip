/** core/parsers.ts — shared parsing logic for the MCP server and UI.
 *
 * Mirrors web/shared.js (the dashboards use the same parsing rules).
 * One core, two frontends: the browser page and the stdio MCP server.
 */

export interface TimingRecord {
  command: string;
  target: string;
  unique_nr: number;
  has_make_level: boolean;
  started_at: string;
  finished_at?: string;
  exit_code?: number;
  tag: "BEGIN" | "END";
}

export interface TargetState {
  target: string;
  attempt: number;
  started_at: Date;
  finished_at?: Date;
  exit_code?: number;
  status: "running" | "succeeded" | "failed" | "pending";
  duration: number;
  command: string;
}

export interface StatusJson {
  attempt: number;
  max_attempts: number;
  pid: number;
  started_at: string;
  make_exit: number;
  status: string;
  heartbeat?: string;
  finished_at?: string;
}

export interface DagNode {
  id: string;
  deps: string[];
  recipe: string;
  avg_duration: number;
  longest_downstream: number;
  depth: number;
}

export interface DagJson {
  targets: DagNode[];
  generated_at: string;
}

export function parseTimingLog(text: string): TimingRecord[] {
  const records: TimingRecord[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      records.push(JSON.parse(trimmed) as TimingRecord);
    } catch {
      // skip malformed lines
    }
  }
  return records;
}

export function reduceToTargets(records: TimingRecord[]): TargetState[] {
  const beginRecords = new Map<number, TimingRecord>();
  const targets: TargetState[] = [];

  for (const rec of records) {
    const key = rec.unique_nr;
    if (rec.tag === "BEGIN") {
      beginRecords.set(key, rec);
      targets.push({
        target: rec.target,
        attempt: 0,
        started_at: new Date(rec.started_at),
        status: "running",
        duration: 0,
        command: rec.command,
      });
    } else if (rec.tag === "END") {
      const begin = beginRecords.get(key);
      if (begin) {
        const ts = targets.find(
          (t) => t.target === rec.target && t.started_at.getTime() === new Date(begin.started_at).getTime()
        );
        if (ts) {
          ts.finished_at = new Date(rec.finished_at || rec.started_at);
          ts.exit_code = rec.exit_code;
          ts.status = rec.exit_code === 0 ? "succeeded" : "failed";
          ts.duration = (ts.finished_at.getTime() - ts.started_at.getTime()) / 1000;
        }
      }
      beginRecords.delete(key);
    }
  }

  return targets;
}

export function getSummary(targets: TargetState[]): {
  succeeded: number;
  failed: number;
  running: number;
  total: number;
  totalDuration: number;
} {
  let succeeded = 0, failed = 0, running = 0, totalDuration = 0;
  for (const t of targets) {
    if (t.status === "succeeded") succeeded++;
    else if (t.status === "failed") failed++;
    else if (t.status === "running") running++;
    totalDuration += t.duration;
  }
  return { succeeded, failed, running, total: succeeded + failed + running, totalDuration };
}
