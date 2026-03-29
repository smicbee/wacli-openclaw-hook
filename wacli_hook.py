#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG = {
    "wacli_bin": "wacli",
    "openclaw_bin": "openclaw",
    "poll_interval_seconds": 45,
    "sync_timeout_seconds": 120,
    "openclaw_timeout_seconds": 120,
    "lookback_minutes_on_boot": 15,
    "state_file": "~/.wacli-hook/state.json",
    "dry_run": True,
    "allow_groups": False,
    "allow_chats": [],
    "deny_chats": [],
    "trigger": {
        "mode": "prefix",  # any|prefix|keyword|regex
        "prefixes": ["!claw", "@clawdia"],
        "keywords": ["clawdia", "openclaw"],
        "regex": []
    },
    "reply": {
        "session_strategy": "per_chat",  # per_chat|global
        "global_session_id": "wacli-hook-global",
        "thinking": "minimal",
        "system_preamble": (
            "Du antwortest als lockerer, hilfreicher Assistent in einem WhatsApp-Chat. "
            "Antworte knapp, natürlich und auf Deutsch. Keine Meta-Erklärungen."
        )
    },
    "dedupe": {
        "processed_id_ttl_hours": 168
    }
}


STOP = False


def log(msg: str) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def run_cmd(cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def parse_json_output(stdout: str) -> Any:
    s = stdout.strip()
    if not s:
        return None
    # Some commands may emit logs before JSON; try last JSON object.
    if s.startswith("{") or s.startswith("["):
        return json.loads(s)
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])\s*$", s)
    if match:
        return json.loads(match.group(1))
    raise ValueError(f"Keine JSON-Antwort erkennbar: {s[:200]}")


def iso_now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_ts(ts: str) -> str:
    # wacli returns ...Z timestamps frequently
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def is_group_jid(jid: str) -> bool:
    return jid.endswith("@g.us")


def chat_allowed(cfg: Dict[str, Any], chat_jid: str) -> bool:
    allow = cfg.get("allow_chats", [])
    deny = cfg.get("deny_chats", [])
    if deny and chat_jid in deny:
        return False
    if allow:
        return chat_jid in allow
    return True


def trigger_match(cfg: Dict[str, Any], text: str) -> bool:
    trigger = cfg.get("trigger", {})
    mode = trigger.get("mode", "any").lower()
    t = (text or "").strip()
    tl = t.lower()

    if mode == "any":
        return bool(t)
    if mode == "prefix":
        prefixes = trigger.get("prefixes", [])
        return any(tl.startswith(str(p).lower()) for p in prefixes)
    if mode == "keyword":
        kws = trigger.get("keywords", [])
        return any(str(k).lower() in tl for k in kws)
    if mode == "regex":
        patterns = trigger.get("regex", [])
        return any(re.search(p, t, flags=re.IGNORECASE) for p in patterns)
    return False


def build_session_id(cfg: Dict[str, Any], chat_jid: str) -> str:
    reply = cfg.get("reply", {})
    strategy = reply.get("session_strategy", "per_chat")
    if strategy == "global":
        return reply.get("global_session_id", "wacli-hook-global")
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", chat_jid)
    return f"wacli-hook-{safe}"[:120]


def run_sync_once(cfg: Dict[str, Any]) -> None:
    cmd = [cfg["wacli_bin"], "sync", "--once", "--json"]
    cp = run_cmd(cmd, timeout=int(cfg.get("sync_timeout_seconds", 120)))
    if cp.returncode != 0:
        raise RuntimeError(f"sync fehlgeschlagen: {cp.stderr.strip() or cp.stdout.strip()}")


def fetch_messages_since(cfg: Dict[str, Any], after_iso: str) -> List[Dict[str, Any]]:
    cmd = [
        cfg["wacli_bin"],
        "messages",
        "list",
        "--after",
        after_iso,
        "--limit",
        "200",
        "--json",
    ]
    cp = run_cmd(cmd, timeout=60)
    if cp.returncode != 0:
        raise RuntimeError(f"messages list fehlgeschlagen: {cp.stderr.strip() or cp.stdout.strip()}")
    payload = parse_json_output(cp.stdout)
    if not isinstance(payload, dict) or not payload.get("success", False):
        raise RuntimeError(f"unerwartete messages-Antwort: {cp.stdout.strip()[:300]}")
    data = payload.get("data", {}) or {}
    msgs = data.get("messages", []) or []
    msgs.sort(key=lambda m: m.get("Timestamp", ""))
    return msgs


def build_agent_prompt(cfg: Dict[str, Any], message: Dict[str, Any]) -> str:
    preamble = cfg.get("reply", {}).get("system_preamble", "")
    return (
        f"{preamble}\n\n"
        f"Kontext:\n"
        f"- ChatJID: {message.get('ChatJID','')}\n"
        f"- SenderJID: {message.get('SenderJID','')}\n"
        f"- Timestamp: {message.get('Timestamp','')}\n"
        f"- Nachricht: {message.get('Text','').strip()}\n\n"
        f"Bitte antworte direkt auf diese Nachricht."
    )


def call_openclaw(cfg: Dict[str, Any], chat_jid: str, incoming: Dict[str, Any]) -> str:
    prompt = build_agent_prompt(cfg, incoming)
    session_id = build_session_id(cfg, chat_jid)
    thinking = cfg.get("reply", {}).get("thinking", "minimal")

    cmd = [
        cfg["openclaw_bin"],
        "agent",
        "--session-id",
        session_id,
        "--message",
        prompt,
        "--thinking",
        str(thinking),
        "--json",
        "--timeout",
        str(int(cfg.get("openclaw_timeout_seconds", 120))),
    ]
    cp = run_cmd(cmd, timeout=int(cfg.get("openclaw_timeout_seconds", 120)) + 20)
    if cp.returncode != 0:
        raise RuntimeError(f"openclaw agent fehlgeschlagen: {cp.stderr.strip() or cp.stdout.strip()}")

    payload = parse_json_output(cp.stdout)
    text = (
        payload.get("result", {})
        .get("payloads", [{}])[0]
        .get("text", "")
    )
    text = (text or "").strip()
    if not text:
        raise RuntimeError("openclaw lieferte keinen Antworttext")
    return text


def send_reply(cfg: Dict[str, Any], to_chat_jid: str, text: str) -> Dict[str, Any]:
    cmd = [
        cfg["wacli_bin"],
        "send",
        "text",
        "--to",
        to_chat_jid,
        "--message",
        text,
        "--json",
    ]
    cp = run_cmd(cmd, timeout=90)
    if cp.returncode != 0:
        raise RuntimeError(f"send fehlgeschlagen: {cp.stderr.strip() or cp.stdout.strip()}")
    payload = parse_json_output(cp.stdout)
    if not isinstance(payload, dict) or not payload.get("success", False):
        raise RuntimeError(f"unerwartete send-Antwort: {cp.stdout.strip()[:300]}")
    return payload


def prune_processed(state: Dict[str, Any], ttl_hours: int) -> None:
    processed = state.get("processed_ids", {})
    if not processed:
        return
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=ttl_hours)
    keep = {}
    for msg_id, ts in processed.items():
        try:
            parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            if parsed >= cutoff:
                keep[msg_id] = ts
        except Exception:
            continue
    state["processed_ids"] = keep


def should_process_message(cfg: Dict[str, Any], msg: Dict[str, Any], state: Dict[str, Any]) -> bool:
    if msg.get("FromMe", False):
        return False
    msg_id = msg.get("MsgID", "")
    if not msg_id:
        return False
    if msg_id in state.get("processed_ids", {}):
        return False
    text = (msg.get("Text") or "").strip()
    if not text:
        return False

    chat_jid = msg.get("ChatJID", "")
    if not chat_jid:
        return False
    if is_group_jid(chat_jid) and not cfg.get("allow_groups", False):
        return False
    if not chat_allowed(cfg, chat_jid):
        return False

    return trigger_match(cfg, text)


def mark_processed(state: Dict[str, Any], msg: Dict[str, Any]) -> None:
    msg_id = msg.get("MsgID")
    if not msg_id:
        return
    state.setdefault("processed_ids", {})[msg_id] = iso_now_utc()


def handle_signal(signum, frame):
    global STOP
    STOP = True
    log(f"Signal {signum} empfangen, beende nach aktuellem Durchlauf...")


def run_loop(cfg: Dict[str, Any], once: bool = False) -> int:
    state_path = Path(os.path.expanduser(cfg.get("state_file", "~/.wacli-hook/state.json")))
    state = load_json(state_path, {})
    processed = state.get("processed_ids")
    if not isinstance(processed, dict):
        state["processed_ids"] = {}

    if "last_check_iso" not in state:
        start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=int(cfg.get("lookback_minutes_on_boot", 15)))
        state["last_check_iso"] = start.replace(microsecond=0).isoformat()

    ttl_hours = int(cfg.get("dedupe", {}).get("processed_id_ttl_hours", 168))

    while True:
        cycle_start = iso_now_utc()
        try:
            run_sync_once(cfg)
            after_iso = state.get("last_check_iso", cycle_start)
            messages = fetch_messages_since(cfg, after_iso)

            handled = 0
            for msg in messages:
                # advance watermark eagerly to avoid reprocessing storms
                ts = msg.get("Timestamp")
                if ts:
                    try:
                        state["last_check_iso"] = normalize_ts(ts)
                    except Exception:
                        pass

                if not should_process_message(cfg, msg, state):
                    continue

                chat_jid = msg["ChatJID"]
                incoming_text = (msg.get("Text") or "").strip()
                log(f"Trigger in {chat_jid}: {incoming_text[:80]}")

                try:
                    reply = call_openclaw(cfg, chat_jid, msg)
                    if cfg.get("dry_run", True):
                        log(f"DRY-RUN reply -> {chat_jid}: {reply[:160]}")
                    else:
                        send_reply(cfg, chat_jid, reply)
                        log(f"Antwort gesendet -> {chat_jid}")
                    mark_processed(state, msg)
                    handled += 1
                except Exception as e:
                    log(f"Antwort fehlgeschlagen für {chat_jid}: {e}")

            state["last_check_iso"] = cycle_start
            prune_processed(state, ttl_hours)
            save_json(state_path, state)
            log(f"Durchlauf fertig: {len(messages)} Nachrichten geprüft, {handled} verarbeitet.")
        except Exception as e:
            log(f"Durchlauf-Fehler: {e}")
            save_json(state_path, state)

        if once or STOP:
            return 0
        time.sleep(int(cfg.get("poll_interval_seconds", 45)))


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return DEFAULT_CONFIG
    user_cfg = load_json(path, {})
    if not isinstance(user_cfg, dict):
        raise ValueError("Config muss ein JSON-Objekt sein")
    return deep_merge(DEFAULT_CONFIG, user_cfg)


def main() -> int:
    parser = argparse.ArgumentParser(description="wacli -> OpenClaw auto-reply hook runner")
    parser.add_argument("--config", default="./config.json", help="Pfad zur JSON-Konfiguration")
    parser.add_argument("--once", action="store_true", help="Nur einen Durchlauf ausführen")
    parser.add_argument("--init-config", action="store_true", help="Beispiel-Config schreiben und beenden")
    args = parser.parse_args()

    cfg_path = Path(args.config).expanduser().resolve()

    if args.init_config:
        if cfg_path.exists():
            print(f"Config existiert bereits: {cfg_path}", file=sys.stderr)
            return 1
        save_json(cfg_path, DEFAULT_CONFIG)
        print(f"Beispiel-Config geschrieben: {cfg_path}")
        return 0

    cfg = load_config(cfg_path)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log(f"Starte wacli-hook (dry_run={cfg.get('dry_run', True)})")
    return run_loop(cfg, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
