// Self-contained Paperclip external adapter plugin: `plateau_local`.
// Runs a spawned agent as a bounded plateau-agency orchestrator+worker fleet
// (fresh-and-discarded `claude -p` workers, bounded signal, checkpoint/resume)
// instead of one linear `claude --print`. See ../README.md.
//
// Self-contained on purpose: the plugin-loader dynamically imports this file;
// keeping it free of cross-package relative imports makes `createServerAdapter`
// resolve reliably under the host's loader. Only node builtins + `import type`.

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type {
  ServerAdapterModule,
  AdapterExecutionContext,
  AdapterExecutionResult,
  AdapterEnvironmentTestContext,
  AdapterEnvironmentTestResult,
} from "@paperclipai/adapter-utils";

const TYPE = "plateau_local";

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

/** Compose the per-agent GOAL for role mode from the agent's own config +
 *  the immediate heartbeat trigger. This is what makes each spawned agent run
 *  ITS role under the orchestrator+worker pattern (instead of a generic repo
 *  audit): the role charter is the goal, the orchestrator decomposes it into
 *  fresh bounded workers. */
function buildRoleGoal(
  config: Record<string, unknown>,
  context: Record<string, unknown>,
  cwd: string,
): string {
  const parts: string[] = [];
  const tmpl = asString(config.promptTemplate);
  if (tmpl) parts.push("# Role charter\n" + tmpl);
  const instrPath = asString(config.instructionsFilePath);
  if (instrPath && existsSync(instrPath)) {
    try {
      parts.push("# Role instructions\n" + readFileSync(instrPath, "utf8").slice(0, 8000));
    } catch { /* unreadable instructions — proceed with charter only */ }
  }
  const trig: string[] = [];
  for (const k of ["taskId", "issueId", "wakeReason", "wakeCommentId", "commentId", "approvalStatus"]) {
    const v = context[k];
    if (typeof v === "string" && v.trim().length > 0) trig.push(`${k}=${v.trim()}`);
  }
  if (trig.length > 0) parts.push("# Current trigger\n" + trig.join("  "));
  parts.push("# Working directory\n" + cwd);
  parts.push(
    "Operate as this role. Make concrete, verifiable progress on the role's responsibilities " +
    "given the current trigger and the repo/workspace state. Prefer real work over planning.",
  );
  return parts.join("\n\n");
}

async function execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult> {
  const { runId, config, context, runtime, onLog, onSpawn } = ctx;

  const workspace = parseObject(context.paperclipWorkspace);
  const cwd = asString(workspace.cwd) || asString(config.cwd) || process.cwd();

  const plateauDir = asString(config.plateauDir);
  if (!plateauDir || !existsSync(plateauDir)) {
    return {
      exitCode: null, signal: null, timedOut: false,
      errorMessage: `plateau_local: config.plateauDir is required and must exist (got "${plateauDir}")`,
      errorCode: "plateau_misconfigured",
    };
  }

  const rawMode = asString(config.mode, "audit");
  const mode = rawMode === "write" || rawMode === "role" ? rawMode : "audit";
  const targetSeconds = asNumber(config.targetSeconds, 7200);
  const maxSteps = asNumber(config.maxSteps, 80);
  const workerModel = asString(config.workerModel);
  const command = asString(config.command, "uv");
  const stub = asBoolean(config.stub, false);
  const includeSource = asBoolean(config.includeSource, false);
  const configPath = asString(config.driverConfigPath);

  const priorParams = parseObject(runtime.sessionParams);
  const priorResume = asString(priorParams.resumePath);
  const canResume = priorResume.length > 0 && existsSync(priorResume);

  // role mode: write the composed per-agent goal to a file the driver reads.
  let goalFile = "";
  if (mode === "role" && !canResume) {
    const goal = buildRoleGoal(config, context, cwd);
    const goalDir = join(plateauDir, ".plateau");
    try { mkdirSync(goalDir, { recursive: true }); } catch { /* exists */ }
    goalFile = join(goalDir, `role-goal-${runId}.txt`);
    try {
      writeFileSync(goalFile, goal, "utf8");
    } catch (err) {
      return {
        exitCode: null, signal: null, timedOut: false,
        errorMessage: `plateau_local: failed to write role goal file: ${(err as Error).message}`,
        errorCode: "plateau_goal_write_failed",
      };
    }
  }

  const args = ["run", "--project", plateauDir, "plateau-agency", "--repo", cwd, "--mode", mode];
  if (canResume) {
    args.push("--resume", priorResume);
  } else {
    args.push("--run-id", runId, "--max-steps", String(maxSteps), "--target-seconds", String(targetSeconds));
    if (mode === "role") {
      args.push("--goal-file", goalFile);
    } else {
      if (includeSource) args.push("--include-source");
      if (configPath) args.push("--config", configPath);
    }
  }
  if (workerModel) args.push("--worker-model", workerModel);
  if (stub) args.push("--stub");

  await ctx.onMeta?.({ adapterType: TYPE, command, cwd, commandArgs: args, context });

  return await new Promise<AdapterExecutionResult>((resolve) => {
    const child = spawn(command, args, { cwd, env: { ...process.env } });
    if (child.pid && onSpawn) {
      void onSpawn({ pid: child.pid, processGroupId: null, startedAt: new Date().toISOString() });
    }
    let lastStatus = "";
    let stopLine = "";
    let nextResumePath = "";
    let stdoutTail = "";

    child.stdout?.on("data", (buf: Buffer) => {
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
    });
    child.stderr?.on("data", (buf: Buffer) => void onLog("stderr", buf.toString()));

    child.on("error", (err) => {
      resolve({
        exitCode: null, signal: null, timedOut: false,
        errorMessage: `plateau_local: failed to spawn "${command}": ${err.message}`,
        errorCode: "plateau_spawn_failed",
      });
    });

    child.on("close", (code, signal) => {
      const checkpointed = stopLine.includes("step_budget_checkpoint") && nextResumePath.length > 0;
      resolve({
        exitCode: code ?? 0,
        signal: signal ?? null,
        timedOut: false,
        summary: stopLine || lastStatus || "plateau-agency run complete",
        sessionParams: checkpointed ? { resumePath: nextResumePath, cwd } : null,
        sessionDisplayId: runId,
        provider: "anthropic",
        billingType: "subscription",
        resultJson: { stopLine, lastStatus, resumePath: nextResumePath, stdoutTail },
        clearSession: !checkpointed,
      });
    });
  });
}

async function testEnvironment(ctx: AdapterEnvironmentTestContext): Promise<AdapterEnvironmentTestResult> {
  const checks: AdapterEnvironmentTestResult["checks"] = [];
  const plateauDir = asString(parseObject(ctx.config).plateauDir);
  if (!plateauDir || !existsSync(plateauDir)) {
    checks.push({ code: "plateau_dir", level: "error", message: "config.plateauDir is missing or does not exist",
      hint: "Point it at the Plateau repo that ships `plateau-agency` (uv project root)." });
  } else {
    checks.push({ code: "plateau_dir", level: "info", message: `Plateau driver dir: ${plateauDir}` });
  }
  const probe = (cmd: string, a: string[]) =>
    new Promise<boolean>((res) => {
      const c = spawn(cmd, a, { stdio: "ignore" });
      c.on("error", () => res(false));
      c.on("close", (code) => res(code === 0));
    });
  if (!(await probe("uv", ["--version"]))) {
    checks.push({ code: "uv", level: "error", message: "`uv` not found on PATH", hint: "Install uv (the driver launcher)." });
  }
  if (!(await probe("claude", ["--version"]))) {
    checks.push({ code: "claude", level: "warn", message: "`claude` CLI not found on PATH", hint: "Workers spawn `claude -p`." });
  }
  const status = checks.some((c) => c.level === "error") ? "fail"
    : checks.some((c) => c.level === "warn") ? "warn" : "pass";
  return { adapterType: TYPE, status, checks, testedAt: new Date().toISOString() };
}

export function createServerAdapter(): ServerAdapterModule {
  return {
    type: TYPE,
    execute,
    testEnvironment,
    agentConfigurationDoc:
      "plateau_local — runs the agent as a bounded plateau-agency orchestrator+worker fleet. " +
      "mode=role (recommended for spawned company agents) composes the agent's goal from its " +
      "promptTemplate + instructionsFilePath + the heartbeat trigger and runs the general bounded " +
      "executor; mode=audit|write run the repo audit/fix loops. " +
      "Config: plateauDir (required, abs path to the Plateau repo), mode (audit|write|role), " +
      "targetSeconds (default 7200), maxSteps, workerModel, includeSource, driverConfigPath, stub.",
  } as unknown as ServerAdapterModule;
}
