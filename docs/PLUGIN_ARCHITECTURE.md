# Plugin Architecture (wacli-hook)

## Goal

`wacli-hook` bridges incoming WhatsApp messages (via `wacli`) into OpenClaw agent replies.

Core idea:
- sync new messages from WhatsApp
- filter by configurable trigger rules
- ask OpenClaw agent to generate a reply
- send the reply back via `wacli`

---

## Components

### 1) Python runner (`wacli_hook.py`)

Long-running orchestrator loop:
1. `wacli sync --once --json`
2. `wacli messages list --after ... --json`
3. filter messages (DM/group, allow/deny, trigger mode)
4. call `openclaw agent --session-id ... --json`
5. `wacli send text --to ... --json`
6. persist state (`last_check_iso`, `processed_ids`)

### 2) OpenClaw plugin wrapper (`index.ts`)

Registers:
- background service `wacli-hook-service`
- tool `wacli_hook_status` (runtime status)
- tool `wacli_hook_run_once` (single-cycle execution)

Service manages Python process lifecycle (start/stop/logging).

### 3) Config

- `config.example.json`: template
- `config.json`: active local runtime config (ignored in git)
- plugin config (`plugins.entries.wacli-hook.config`) can override script/config paths

---

## Trigger model

Supported trigger modes:
- `any`: every inbound text
- `prefix`: message starts with one of configured prefixes
- `keyword`: text contains configured keyword
- `regex`: one of configured regex patterns matches

Recommended production default:
- `prefix` (e.g. `!claw`) to reduce accidental auto-replies.

---

## Dedupe and idempotency

To avoid duplicate answers:
- `processed_ids[msgId] = timestamp`
- configurable TTL cleanup (`processed_id_ttl_hours`)
- watermark (`last_check_iso`) advances per loop

---

## Reliability constraints

`wacli` store lock prevents parallel `sync --follow` + `send` in separate processes.

This project intentionally uses:
- short serial cycles (`sync --once`) instead of persistent `sync --follow`
- one orchestrator process for both read and write

---

## Security & guardrails

- default `dry_run=true`
- default `allow_groups=false`
- allowlist/denylist chat filters
- can enforce trigger prefixes for explicit invocation

Before broad rollout:
- keep strict trigger mode
- enable per-chat cooldowns / global rate limits
- explicitly exclude sensitive chats

---

## Known current limits

- relies on external CLIs (`wacli`, `openclaw`, `python3`) on PATH
- currently process-level orchestration (no native in-process WA integration)
- answer quality/latency depends on current OpenClaw model load and limits

---

## Next hardening milestones

1. per-chat and global reply rate limiting
2. richer audit log (reason for trigger/skip)
3. admin control commands (`pause`, `resume`, `status`)
4. packaging validation in CI (plugin + python runner smoke tests)
