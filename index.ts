import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { dirname } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

type PluginConfig = {
  enabled?: boolean;
  autoStart?: boolean;
  pythonBin?: string;
  scriptPath?: string;
  configPath?: string;
};

type ServiceState = {
  running: boolean;
  pid?: number;
  startedAt?: string;
  lastExitCode?: number | null;
  lastExitSignal?: NodeJS.Signals | null;
  lastError?: string;
};

function toPrettyJson(data: unknown): string {
  return JSON.stringify(data, null, 2);
}

function runOnce(params: {
  pythonBin: string;
  scriptPath: string;
  configPath: string;
  timeoutMs: number;
}): Promise<{ ok: boolean; exitCode: number | null; signal: NodeJS.Signals | null; stdout: string; stderr: string }> {
  const { pythonBin, scriptPath, configPath, timeoutMs } = params;
  return new Promise((resolve) => {
    const child = spawn(pythonBin, [scriptPath, "--config", configPath, "--once"], {
      cwd: dirname(scriptPath),
      stdio: ["ignore", "pipe", "pipe"],
      env: process.env,
    });

    let stdout = "";
    let stderr = "";
    let killedByTimeout = false;

    const timer = setTimeout(() => {
      killedByTimeout = true;
      child.kill("SIGKILL");
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });

    child.on("close", (code, signal) => {
      clearTimeout(timer);
      if (killedByTimeout) {
        resolve({ ok: false, exitCode: code, signal, stdout, stderr: `${stderr}\nTimed out after ${timeoutMs}ms`.trim() });
        return;
      }
      resolve({ ok: code === 0, exitCode: code, signal, stdout, stderr });
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ ok: false, exitCode: null, signal: null, stdout, stderr: `${stderr}\n${String(err)}`.trim() });
    });
  });
}

export default definePluginEntry({
  id: "wacli-hook",
  name: "wacli Hook",
  description: "Runs the wacli->OpenClaw auto-reply hook script as a managed plugin service",
  register(api) {
    const cfg = (api.pluginConfig ?? {}) as PluginConfig;

    const enabled = cfg.enabled ?? true;
    const autoStart = cfg.autoStart ?? true;
    const pythonBin = cfg.pythonBin ?? "python3";
    const scriptPath = cfg.scriptPath ?? api.resolvePath("wacli_hook.py");
    const configPath = cfg.configPath ?? api.resolvePath("config.json");

    let child: ChildProcessWithoutNullStreams | null = null;
    const state: ServiceState = {
      running: false,
      lastExitCode: null,
      lastExitSignal: null,
    };

    const startService = () => {
      if (!enabled) {
        api.logger.info("wacli-hook disabled by config", { pluginId: api.id });
        return;
      }
      if (!autoStart) {
        api.logger.info("wacli-hook autoStart=false; service not started", { pluginId: api.id });
        return;
      }
      if (child) {
        api.logger.info("wacli-hook service already running", { pid: child.pid });
        return;
      }

      child = spawn(pythonBin, [scriptPath, "--config", configPath], {
        cwd: dirname(scriptPath),
        stdio: ["ignore", "pipe", "pipe"],
        env: process.env,
      });

      state.running = true;
      state.pid = child.pid;
      state.startedAt = new Date().toISOString();
      state.lastError = undefined;

      api.logger.info("wacli-hook service started", {
        pid: child.pid,
        pythonBin,
        scriptPath,
        configPath,
      });

      child.stdout.on("data", (chunk) => {
        const text = String(chunk).trim();
        if (text) api.logger.info(`[wacli-hook] ${text}`);
      });
      child.stderr.on("data", (chunk) => {
        const text = String(chunk).trim();
        if (text) api.logger.warn(`[wacli-hook] ${text}`);
      });

      child.on("close", (code, signal) => {
        state.running = false;
        state.lastExitCode = code;
        state.lastExitSignal = signal;
        state.pid = undefined;
        child = null;
        api.logger.warn("wacli-hook service exited", { code, signal });
      });

      child.on("error", (err) => {
        state.lastError = String(err);
        api.logger.error("wacli-hook service error", { error: String(err) });
      });
    };

    const stopService = () => {
      if (!child) return;
      try {
        child.kill("SIGTERM");
      } catch (err) {
        api.logger.warn("failed to stop wacli-hook service", { error: String(err) });
      }
    };

    api.registerService({
      id: "wacli-hook-service",
      async start() {
        startService();
      },
      async stop() {
        stopService();
      },
    });

    api.registerTool(
      {
        name: "wacli_hook_status",
        description: "Get runtime status of the managed wacli hook service",
        parameters: {
          type: "object" as const,
          properties: {},
          required: [],
        },
        async execute() {
          return toPrettyJson({
            enabled,
            autoStart,
            pythonBin,
            scriptPath,
            configPath,
            ...state,
          });
        },
      },
      { optional: true, names: ["wacli_hook_status"] },
    );

    api.registerTool(
      {
        name: "wacli_hook_run_once",
        description: "Execute one sync/process cycle of the wacli hook script",
        parameters: {
          type: "object" as const,
          properties: {
            timeoutMs: { type: "number", description: "Max runtime in milliseconds (default 120000)" },
          },
          required: [],
        },
        async execute(_toolCallId: string, params: { timeoutMs?: number }) {
          const timeoutMs = Number.isFinite(params?.timeoutMs) ? Math.max(1_000, Math.floor(params.timeoutMs!)) : 120_000;
          const result = await runOnce({
            pythonBin,
            scriptPath,
            configPath,
            timeoutMs,
          });
          return toPrettyJson(result);
        },
      },
      { optional: true, names: ["wacli_hook_run_once"] },
    );
  },
});
