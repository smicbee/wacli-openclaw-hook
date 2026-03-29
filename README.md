# wacli-openclaw-hook

Automates WhatsApp message handling by combining:

- `wacli` for sync + send
- `openclaw agent` for generated replies
- a lightweight OpenClaw plugin wrapper for lifecycle/status tooling

---

## Repository contents

- `wacli_hook.py` — main orchestration runner
- `config.example.json` — starter config
- `index.ts` — OpenClaw plugin entry (`wacli-hook`)
- `openclaw.plugin.json` — plugin manifest + schema
- `package.json` — package metadata for plugin publishing
- `docs/PLUGIN_ARCHITECTURE.md` — detailed architecture
- `docs/RELEASE_PLAN.md` — release checklist and rollout plan

---

## How it works

The runner executes a serial loop:

1. `wacli sync --once --json`
2. fetch new messages (`wacli messages list --after ...`)
3. trigger/filter evaluation
4. call `openclaw agent --session-id ... --json`
5. send reply via `wacli send text`
6. persist state (watermark + dedupe)

This avoids `wacli` store-lock issues seen with parallel `sync --follow` + `send` usage.

---

## Quickstart

```bash
cd /home/smicbee/repos/wacli-openclaw-hook
cp config.example.json config.json
python3 wacli_hook.py --config ./config.json --once
```

Default is `dry_run=true`, so nothing is sent.

When validated:

```bash
# set "dry_run": false in config.json
python3 wacli_hook.py --config ./config.json
```

---

## Plugin usage

The repo also ships an OpenClaw plugin entry (`wacli-hook`) that can manage the runner as a service and expose helper tools:

- `wacli_hook_status`
- `wacli_hook_run_once`

Example plugin config (in OpenClaw config):

```json
{
  "plugins": {
    "entries": {
      "wacli-hook": {
        "enabled": true,
        "config": {
          "enabled": true,
          "autoStart": true,
          "pythonBin": "python3",
          "scriptPath": "/home/smicbee/repos/wacli-openclaw-hook/wacli_hook.py",
          "configPath": "/home/smicbee/repos/wacli-openclaw-hook/config.json"
        }
      }
    }
  }
}
```

---

## Recommended production defaults

- trigger mode: `prefix`
- prefixes: `!claw` (or explicit mention pattern)
- `allow_groups=false` unless explicitly needed
- strict allowlist for auto-reply chats

---

## Notes

- Requires `wacli`, `openclaw`, and `python3` on PATH.
- `config.json` is intentionally git-ignored.
- Start with dry-run and move to live replies only after end-to-end validation.
