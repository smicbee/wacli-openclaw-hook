# wacli-openclaw-hook

Kleiner Runner, der eingehende WhatsApp-Nachrichten über `wacli` erkennt und bei Triggern automatisch `openclaw agent` aufruft, um Antworten zu generieren.

## Was das Script macht

1. Führt regelmäßig `wacli sync --once` aus (kein dauerhaftes `--follow`, damit kein Store-Lock blockiert).
2. Liest neue Nachrichten via `wacli messages list --after ... --json`.
3. Filtert nach konfigurierbaren Regeln (Chat, DM/Group, Trigger).
4. Ruft `openclaw agent --session-id ... --json` auf.
5. Sendet Antwort per `wacli send text --to <chatJID>`.
6. Speichert State (`last_check_iso`, `processed_ids`) für Dedupe.

## Voraussetzungen

- `wacli` ist eingerichtet (`wacli auth` bereits gelaufen)
- `openclaw` CLI ist installiert und gegen laufendes Gateway nutzbar
- Python 3.10+

## Schnellstart

```bash
cd /home/smicbee/repos/wacli-openclaw-hook
cp config.example.json config.json
python3 wacli_hook.py --config ./config.json --once
```

Standardmäßig läuft es mit `dry_run=true` (es wird **nicht** gesendet).

Wenn die Logs passen:

```bash
# config.json: "dry_run": false setzen
python3 wacli_hook.py --config ./config.json
```

## Wichtige Config-Felder

- `dry_run`: true = nur simulieren, false = wirklich senden
- `allow_groups`: Gruppen erlauben (default false)
- `allow_chats`: wenn gesetzt, nur diese ChatJIDs erlauben
- `trigger.mode`: `any` | `prefix` | `keyword` | `regex`
- `reply.session_strategy`: `per_chat` oder `global`
- `reply.thinking`: Thinking-Level für `openclaw agent`

## Beispiel: nur auf Prefix `!claw` in DMs reagieren

```json
{
  "dry_run": false,
  "allow_groups": false,
  "trigger": {
    "mode": "prefix",
    "prefixes": ["!claw"]
  }
}
```

## Betrieb als Systemd User Service (optional)

`~/.config/systemd/user/wacli-hook.service`:

```ini
[Unit]
Description=wacli -> OpenClaw hook runner
After=default.target

[Service]
Type=simple
WorkingDirectory=/home/smicbee/repos/wacli-openclaw-hook
ExecStart=/usr/bin/python3 /home/smicbee/repos/wacli-openclaw-hook/wacli_hook.py --config /home/smicbee/repos/wacli-openclaw-hook/config.json
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Aktivieren:

```bash
systemctl --user daemon-reload
systemctl --user enable --now wacli-hook.service
journalctl --user -u wacli-hook.service -f
```

## Hinweise

- Während ein `sync --follow` läuft, blockiert `wacli` den Store. Dieses Script nutzt daher bewusst `sync --once` pro Zyklus.
- Für Sicherheit zuerst immer mit `dry_run=true` testen.
- Trigger und Allowlist streng halten, damit nichts ungeplant antwortet.
