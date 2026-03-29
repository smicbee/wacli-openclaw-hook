# Release Plan (Plugin Publishing)

## Short term (current)

- Repository contains:
  - OpenClaw plugin entry (`index.ts`)
  - plugin manifest (`openclaw.plugin.json`)
  - python runner (`wacli_hook.py`)
  - docs and sample config
- Goal: stable private testing with real chats

## Pre-public checklist

1. **Runtime safety**
   - `dry_run=false` only after trigger rules are strict
   - test denylist/allowlist paths
   - verify no self-reply loops

2. **Dependency checks**
   - `python3 --version`
   - `wacli doctor`
   - `openclaw status`

3. **Functional tests**
   - DM trigger -> reply
   - non-trigger message -> no reply
   - duplicate inbound message -> no duplicate answer
   - process restart -> state recovery

4. **Documentation**
   - installation instructions
   - config field reference
   - known limitations + recommended defaults

5. **Versioning**
   - bump `package.json` version
   - tag release

## Publishing options

- GitHub release first
- optional npm publish later (already package-ready)
- optional ClawHub publication after stable soak period

## Collaboration model

- keep `main` deployable
- use feature branches for risky changes
- require quick smoke test before merge
