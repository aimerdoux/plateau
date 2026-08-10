// Paperclip server adapter: `plateau_local`
//
// Runs a spawned agent on the PLATEAU PATTERN instead of a single linear
// `claude --print`. Each activation drives the validated `plateau-agency`
// orchestrator loop (driver.py): the orchestrator's entire memory is a bounded
// signal.json; every step spawns a FRESH `claude -p` worker (clean context),
// gates its one-JSON result deterministically, persists, and discards it. The
// orchestrator context never grows — so the agent sustains long-horizon work
// (the driver's WALL_CLOCK_CEIL is 3h; --target-seconds defaults to 2h here)
// without the context-bloat / max-turns collapse that linear execution hits.
//
// Cross-activation continuity is the bounded RESUME.json (a few KB), NOT a
// growing Claude session: on checkpoint the driver prints a resume path, which
// we stash in sessionParams so the next heartbeat picks up exactly where it
// stopped — bounded context, indefinitely.
//
// Downstream worker prompting is the repo's own technique (plateau/agency/
// prompts.py: SAFETY_FLOOR + build_subtask + RETURN_CONTRACT). This adapter is
// a thin process shell; the driver does the work.
//
// ADDITIVE: landing this changes no existing agent. To adopt, register the type
// (see README in this dir) and point an agent's adapterType at "plateau_local".

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import type {
  AdapterExecutionContext,
  AdapterExecutionResult,
  AdapterEnvironmentTestContext,
  AdapterEnvironmentTestResult,
} from "@paperclipai/adapter-utils";

export const type = "plateau_local";
export const label = "Plateau fleet (local)";

export const agentConfigurationDoc = `# plateau_local agent configuration

Adapter: plateau_local — runs the agent as a bounded orchestrator+worker fleet
(plateau-agency) instead of a single linear Claude run.

Core fields:
- cwd (string, optional): repo the fleet operates on; falls back to the realized
  Paperclip workspace cwd, then process.cwd().
- plateauDir (string, required): absolute path to the Plateau repo that provides
  the \`plateau-agency\` driver (e.g. /Users/geniex/bmacp-trunk/plateau).
- mode ("audit" | "write", optional, default "audit"): audit = read-only workers
  (no git/gh/supabase tools, nothing is committed); write = workers may apply the
  smallest gated fix and the driver opens PRs (never pushes to main).
- targetSeconds (number, optional, default 7200): long-horizon budget per the
  driver; it checkpoints at maxSteps and resumes across activations.
- maxSteps (number, optional, default 80): per-activation step budget.
- workerModel (string, optional): model for the fresh \`claude -p\` workers (cost
  lever); requires the driver's --worker-model passthrough.
- command (string, optional, default "uv"): launcher; args run the driver via
  \`uv run --project <plateauDir> plateau-agency ...\`.
- stub (boolean, optional): canned worker result, no Claude call ($0 machinery test).
`;

function asString(v: unknown, d = ""): string {
  return typeof v === "string" && v.length > 0 ? v : d;
}
function asNumber(v: unknown, d: number): number {
  return typeof v === "number" && Number.isFinite(v) ? v : d;
}
function asBoolean(v: unknown, d = false): boolean {
  return typeof v === "boolean" ? v : d;
}
function parseObject(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

export async function execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult> {
  const { runId, config, context, runtime, onLog, onSpawn } = ctx;

  const workspace = parseObject(context.paperclipWorkspace);
  const cwd = asString(workspace.cwd) || asString(config.cwd) || process.cwd();

  const plateauDir = asString(config.plateauDir);
  if (!plateauDir || !existsSync(plateauDir)) {
    return {
      exitCode: null,
      signal: null,
      timedOut: false,
      errorMessage: `plateau_local: config.plateauDir is required and must exist (got "${plateauDir}")`,
      errorCode: "plateau_misconfigured",
    };
  }

  const mode = asString(config.mode, "audit") === "write" ? "write" : "audit";
  const targetSeconds = asNumber(config.targetSeconds, 7200);
  const maxSteps = asNumber(config.maxSteps, 80);
  const workerModel = asString(config.workerModel);
  const command = asString(config.command, "uv");
  const stub = asBoolean(config.stub, false);

  // Cross-activation continuity: resume the prior bounded checkpoint if present.
  const priorParams = parseObject(runtime.sessionParams);
  const priorResume = asString(priorParams.resumePath);
  const canResume = priorResume.length > 0 && existsSync(priorResume);

  const args = ["run", "--project", plateauDir, "plateau-agency", "--repo", cwd, "--mode", mode];
  if (canResume) {
    args.push("--resume", priorResume);
  } else {
    args.push("--run-id", runId, "--max-steps", String(maxSteps), "--target-seconds", String(targetSeconds));
  }
  if (workerModel) args.push("--worker-model", workerModel);
  if (stub) args.push("--stub");

  await ctx.onMeta?.({ adapterType: type, command, cwd, commandArgs: args, context });

  return await new Promise<AdapterExecutionResult>((resolve) => {
    const child = spawn(command, args, { cwd, env: { ...process.env } });
    if (child.pid && onSpawn) {
      void onSpawn({ pid: child.pid, processGroupId: null, startedAt: new Date().toISOString() });
    }

    let lastStatus = "";        // last `step ...` line — the live KPI tail
    let stopLine = "";          // STOP reason=... — the run summary
    let nextResumePath = "";    // RESUME.json path printed on checkpoint
    let stdoutTail = "";

    const onStdout = (buf: Buffer) => {
      const text = buf.toString();
      stdoutTail = (stdoutTail + text).slice(-4000);
      void onLog("stdout", text);
      for (const line of text.split(/\r?\n/)) {
        const t = line.trim();
        if (t.startsWith("step ")) lastStatus = t;
        else if (t.startsWith("STOP ")) stopLine = t;
        else if (t.includes("--resume ")) {
          const m = t.match(/--resume\s+(\S+)/);
          if (m) nextResumePath = m[1];
        }
      }
    };
    child.stdout?.on("data", onStdout);
    child.stderr?.on("data", (buf: Buffer) => void onLog("stderr", buf.toString()));

    child.on("error", (err) => {
      resolve({
        exitCode: null,
        signal: null,
        timedOut: false,
        errorMessage: `plateau_local: failed to spawn "${command}": ${err.message}`,
        errorCode: "plateau_spawn_failed",
      });
    });

    child.on("close", (code, signal) => {
      // Checkpointed (budget hit, more work remains) -> keep the bounded resume
      // pointer so the next activation continues. Drained/clean -> clear it.
      const checkpointed = stopLine.includes("step_budget_checkpoint") && nextResumePath.length > 0;
      const sessionParams = checkpointed ? { resumePath: nextResumePath, cwd } : null;
      resolve({
        exitCode: code ?? 0,
        signal: signal ?? null,
        timedOut: false,
        summary: stopLine || lastStatus || "plateau-agency run complete",
        sessionParams,
        sessionDisplayId: runId,
        provider: "anthropic",
        billingType: "subscription",
        resultJson: { stopLine, lastStatus, resumePath: nextResumePath, stdoutTail },
        // Drained backlog means the long-horizon task is done; clear the session
        // so a fresh activation re-seeds rather than resuming a finished run.
        clearSession: !checkpointed,
      });
    });
  });
}

export async function testEnvironment(
  ctx: AdapterEnvironmentTestContext,
): Promise<AdapterEnvironmentTestResult> {
  const checks: AdapterEnvironmentTestResult["checks"] = [];
  const plateauDir = asString(parseObject(ctx.config).plateauDir);

  if (!plateauDir || !existsSync(plateauDir)) {
    checks.push({
      code: "plateau_dir",
      level: "error",
      message: "config.plateauDir is missing or does not exist",
      hint: "Point it at the Plateau repo that ships `plateau-agency` (uv project root).",
    });
  } else {
    checks.push({ code: "plateau_dir", level: "info", message: `Plateau driver dir: ${plateauDir}` });
  }

  const probe = (cmd: string, args: string[]) =>
    new Promise<boolean>((res) => {
      const c = spawn(cmd, args, { stdio: "ignore" });
      c.on("error", () => res(false));
      c.on("close", (code) => res(code === 0));
    });

  if (!(await probe("uv", ["--version"]))) {
    checks.push({ code: "uv", level: "error", message: "`uv` not found on PATH", hint: "Install uv (the driver launcher)." });
  }
  if (!(await probe("claude", ["--version"]))) {
    checks.push({ code: "claude", level: "warn", message: "`claude` CLI not found on PATH", hint: "Workers spawn `claude -p`; install/login the Claude CLI." });
  }

  const status = checks.some((c) => c.level === "error")
    ? "fail"
    : checks.some((c) => c.level === "warn")
      ? "warn"
      : "pass";
  return { adapterType: type, status, checks, testedAt: new Date().toISOString() };
}
