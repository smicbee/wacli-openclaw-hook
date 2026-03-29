# wacli-openclaw-hook

`wacli-openclaw-hook` is a neutral automation plugin/runner that connects incoming WhatsApp messages (via `wacli`) with OpenClaw agent replies.

It is designed for controlled auto-reply workflows with explicit trigger rules, deduplication, and dry-run safety.

---

## What this project does

The runner executes a serialized loop:

1. sync messages from WhatsApp (`wacli sync --once`)
2. fetch new messages since the last watermark
3. apply trigger and chat filters
4. generate a response using `openclaw agent`
5. send the response using `wacli send text`
6. persist state for dedupe and restart safety (composite key: `ChatJID::MsgID`)

This avoids common lock conflicts from running long-lived `wacli sync --follow` in parallel with separate send commands.

---

## Repository structure

- `wacli_hook.py` — Python orchestration runner
- `config.example.json` — sample runtime configuration
- `index.ts` — OpenClaw plugin entry
- `openclaw.plugin.json` — plugin manifest and config schema
- `package.json` — package metadata
- `docs/PLUGIN_ARCHITECTURE.md` — architecture reference
- `docs/RELEASE_PLAN.md` — release checklist

---

## Prerequisites

- Node.js 22+
- Python 3.10+
- `wacli` installed and authenticated (`wacli auth` completed)
- OpenClaw installed and reachable from CLI (`openclaw status`)

---

## Installation (local checkout)

```bash
git clone <your-repo-url>
cd wacli-openclaw-hook
cp config.example.json config.json
```

Optional sanity check:

```bash
python3 -m py_compile wacli_hook.py
python3 wacli_hook.py --config ./config.json --once
```

By default, `dry_run` is `true`, so no outbound messages are sent.

---

## Running the runner directly

Single cycle:

```bash
python3 wacli_hook.py --config ./config.json --once
```

Continuous mode:

```bash
python3 wacli_hook.py --config ./config.json
```

---

## Using it as an OpenClaw plugin

The plugin entry (`index.ts`) can run the Python runner as a managed background service.

Example OpenClaw config snippet:

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
          "scriptPath": "./wacli_hook.py",
          "configPath": "./config.json"
        }
      }
    }
  }
}
```

Plugin helper tools:

- `wacli_hook_status`
- `wacli_hook_run_once`

---

## Recommended production defaults

- `trigger.mode = "prefix"`
- use explicit prefixes (for example: `!bot`)
- keep `allow_groups = false` unless required
- use `allow_chats` for strict scope control
- keep `dry_run = true` until end-to-end validation is complete

---

## Security and operational notes

- `config.json` is intentionally git-ignored.
- Do not commit private chat identifiers or credentials.
- Start with restricted triggers and chat allowlists.
- Add rate limits/cooldowns before broad deployment.

---

## License

MIT (see `LICENSE`).
