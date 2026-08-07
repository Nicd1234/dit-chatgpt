#!/usr/bin/env python3
"""Boucle vocale locale NyxPulse.

Mode gratuit/local:
- Vosk pour la reconnaissance vocale hors ligne.
- espeak pour une reponse vocale simple.
- NAS Nyxeos pour journaliser les activations et demandes.

Ce module ne contacte pas ChatGPT/OpenAI. Le mot "chatgpt" est traite ici
comme phrase d'activation utilisateur pour rester gratuit et local.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
except Exception as exc:  # pragma: no cover
    KaldiRecognizer = None
    Model = None
    SetLogLevel = None
    VOSK_IMPORT_ERROR = exc
else:
    VOSK_IMPORT_ERROR = None

try:
    from nyx_cluster_config import NAS_MOUNT
except Exception:
    NAS_MOUNT = "/mnt/nyxeos_nas"


SAMPLE_RATE = 16000
DEFAULT_MODEL = Path(os.environ["DIT_CHATGPT_MODEL"]) if os.environ.get("DIT_CHATGPT_MODEL") else Path(NAS_MOUNT) / "models" / "vosk" / "vosk-model-small-fr-0.22"
FALLBACK_SERVER_MODEL = Path("/srv/nyxeos/models/vosk/vosk-model-small-fr-0.22")
WAKE_PHRASES = ("dit chat g p t", "chat g p t", "dit chatgpt", "chatgpt")
VOSK_GRAMMAR_PHRASES = ("dit chat g p t", "chat g p t", "[unk]")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def active_model_path(path: str | None = None) -> Path:
    if path:
        return Path(path)
    if DEFAULT_MODEL.exists():
        return DEFAULT_MODEL
    return FALLBACK_SERVER_MODEL


def run_command(command: list[str], timeout: int = 10) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return False, str(exc)


def write_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def log_activation(text: str, status: str = "ok") -> dict[str, Any]:
    host = socket.gethostname()
    event = {
        "timestamp": now(),
        "source": host,
        "target": "nyxpulse_voice",
        "action": "wake_phrase",
        "detail": text,
        "status": status,
    }
    for base in (Path(NAS_MOUNT), Path("/srv/nyxeos")):
        try:
            write_jsonl(base / "logs" / "nyx_interactions.jsonl", event)
            break
        except OSError:
            continue

    request = {
        "id": f"voice-{int(time.time())}",
        "timestamp": event["timestamp"],
        "from": host,
        "to": "max",
        "request": "activation vocale locale NyxPulse",
        "heard": text,
        "status": "queued_on_nas",
    }
    for base in (Path(NAS_MOUNT), Path("/srv/nyxeos")):
        try:
            write_jsonl(base / "inbox" / "max_requests.jsonl", request)
            break
        except OSError:
            continue

    try:
        from nyx_memory import remember

        remember("nyxpulse_voice_activation", request, source=f"nyxpulse_voice:{host}")
    except Exception as exc:
        print(f"[nyxpulse_voice_local] memoire indisponible: {exc}")
    return request


def speak(text: str) -> None:
    if not text:
        return
    ok, _ = run_command(["/usr/bin/env", "sh", "-lc", "command -v espeak"], timeout=3)
    if ok:
        subprocess.Popen(["espeak", "-v", "fr", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def recognizer(model_path: Path):
    if VOSK_IMPORT_ERROR is not None or Model is None or KaldiRecognizer is None:
        raise RuntimeError(f"vosk indisponible: {VOSK_IMPORT_ERROR}")
    if not model_path.exists():
        raise FileNotFoundError(f"modele Vosk absent: {model_path}")
    if SetLogLevel:
        SetLogLevel(-1)
    grammar = json.dumps(list(VOSK_GRAMMAR_PHRASES), ensure_ascii=False)
    return KaldiRecognizer(Model(str(model_path)), SAMPLE_RATE, grammar)


def extract_text(result: str) -> str:
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return ""
    return str(data.get("text") or data.get("partial") or "").lower().strip()


def is_wake(text: str) -> bool:
    compact = text.lower().replace("-", " ")
    nospace = compact.replace(" ", "")
    return any(phrase in compact for phrase in WAKE_PHRASES) or "ditchatgpt" in nospace or "chatgpt" in nospace


def listen(model_path: Path, once: bool = False) -> int:
    rec = recognizer(model_path)
    command = ["arecord", "-q", "-r", str(SAMPLE_RATE), "-f", "S16_LE", "-c", "1", "-t", "raw", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f"NyxPulse vocal local en ecoute sur {socket.gethostname()} avec {model_path}")
    try:
        while True:
            if process.stdout is None:
                return 2
            chunk = process.stdout.read(4000)
            if not chunk:
                return 2
            if rec.AcceptWaveform(chunk):
                text = extract_text(rec.Result())
                if text:
                    print(f"entendu: {text}")
                if is_wake(text):
                    request = log_activation(text)
                    speak("NyxPulse actif. Demande transmise au MAX.")
                    print(json.dumps(request, ensure_ascii=False, sort_keys=True))
                    if once:
                        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def self_test(model_path: Path) -> int:
    if VOSK_IMPORT_ERROR is not None:
        print(f"self-test Vosk impossible: {VOSK_IMPORT_ERROR}")
        return 2
    rec = recognizer(model_path)
    tmp = Path("/tmp") / f"nyxpulse_selftest_{os.getpid()}.wav"
    ok, output = run_command(["espeak", "-v", "fr", "-w", str(tmp), "dit chat g p t"], timeout=10)
    if not ok:
        print(f"self-test espeak impossible: {output}")
        return 2
    try:
        with wave.open(str(tmp), "rb") as wav:
            if wav.getframerate() != SAMPLE_RATE:
                print(f"self-test wav rate {wav.getframerate()} Hz; modele charge OK")
                return 0
            while True:
                data = wav.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
        text = extract_text(rec.FinalResult())
        print(json.dumps({"model": str(model_path), "recognized": text, "wake": is_wake(text)}, ensure_ascii=False))
        return 0
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="NyxPulse vocal local gratuit")
    parser.add_argument("--model", help="chemin du modele Vosk")
    parser.add_argument("--listen", action="store_true", help="ecouter le micro")
    parser.add_argument("--once", action="store_true", help="quitter apres la premiere activation")
    parser.add_argument("--self-test", action="store_true", help="charger le modele et tester espeak")
    args = parser.parse_args()

    model_path = active_model_path(args.model)
    if args.self_test:
        return self_test(model_path)
    if args.listen:
        return listen(model_path, once=args.once)
    print(f"Modele: {model_path}")
    print("Utilise --self-test ou --listen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
