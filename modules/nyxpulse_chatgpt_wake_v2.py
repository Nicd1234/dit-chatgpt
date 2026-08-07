#!/usr/bin/env python3
"""Déclencheur vocal local « Dis ChatGPT » pour Nyxeos."""

from __future__ import annotations

import argparse
import array
import json
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
except ImportError:
    KaldiRecognizer = None
    Model = None
    SetLogLevel = None

from nyxpulse_voice_local import active_model_path, is_wake


SAMPLE_RATE = 16000
DETECTION_GAIN = 8.0
POST_STOP_START_GUARD = 20.0
AEC_SOURCE = "nyxeos_vosk_aec"
GRAMMAR = (
    "dit chat g p t",
    "dis chat g p t",
    "dit chat j'ai pété",
    "dis chat j'ai pété",
    "dit chat gé pé té",
    "dis chat gé pé té",
    "dit chat g p t arrête",
    "dis chat g p t arrête",
    "dit chat j'ai pété arrête",
    "dis chat j'ai pété arrête",
    "dit chat gé pé té arrête",
    "dis chat gé pé té arrête",
    "[unk]",
)
STOP_WORDS = ("arrête", "arrete", "stop", "quitte", "termine")
CONTROLLER = Path(__file__).with_name("nyx_chatgpt_voice_controller_v2.py")
LOCAL_LOG = Path("/home/nic/nyxeos_pi5/nyxeos_pi/logs/nyxpulse_chatgpt_wake_v2.jsonl")
START_SOUND = Path("/usr/share/sounds/freedesktop/stereo/message.oga")
STOP_SOUND = Path("/usr/share/sounds/freedesktop/stereo/complete.oga")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def amplify_pcm16(chunk: bytes, gain: float = DETECTION_GAIN) -> bytes:
    samples = array.array("h")
    samples.frombytes(chunk)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        samples[index] = max(-32768, min(32767, round(sample * gain)))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def classify_command(text: str) -> str | None:
    normalized = normalize(text)
    words = normalized.split()
    has_prefix = any(word in ("dit", "dis", "dix") for word in words)
    phonetic_chatgpt = "chat j'ai pété" in normalized or "chat gé pé té" in normalized
    if (not is_wake(normalized) and not phonetic_chatgpt) or not has_prefix:
        return None
    if any(word in normalized for word in STOP_WORDS):
        return "stop"
    return "start"


def contains_chat_token(text: str) -> bool:
    normalized = normalize(text)
    return "chat" in normalized or "g p t" in normalized or "gé pé té" in normalized


def contains_stop_token(text: str) -> bool:
    normalized = normalize(text)
    return any(word in normalized for word in STOP_WORDS)


def is_single_utterance_stop(text: str) -> bool:
    return contains_chat_token(text) and contains_stop_token(text)


def should_dispatch_start(text: str, accepted: bool) -> bool:
    return accepted and classify_command(text) == "start"


def voice_capture_active() -> bool:
    result = subprocess.run(
        ["pactl", "list", "source-outputs"],
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        return False
    return any(
        'application.name = "Chromium input"' in block
        and "Corked: no" in block
        and "Mute: no" in block
        for block in result.stdout.split("Source Output #")
    )


def wake_source() -> str:
    result = subprocess.run(
        ["pactl", "list", "short", "sources"],
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )
    if result.returncode == 0 and any(
        line.split()[1] == AEC_SOURCE
        for line in result.stdout.splitlines()
        if len(line.split()) > 1
    ):
        return AEC_SOURCE
    return "@DEFAULT_SOURCE@"


def write_event(action: str, heard: str, status: str, detail: str = "") -> None:
    event: dict[str, Any] = {
        "timestamp": now(),
        "host": socket.gethostname(),
        "module": "nyxpulse_chatgpt_wake_v2",
        "action": action,
        "heard": heard,
        "status": status,
        "detail": detail,
    }
    LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def play_cue(action: str) -> None:
    sound = START_SOUND if action == "start" else STOP_SOUND
    if sound.exists():
        subprocess.Popen(
            ["paplay", str(sound)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def dispatch(action: str, heard: str, wait: bool = False) -> subprocess.Popen[str] | int:
    play_cue(action)
    command = ["/usr/bin/python3", str(CONTROLLER), action]
    write_event(action, heard, "dispatched")
    if wait:
        result = subprocess.run(command, text=True, capture_output=True, timeout=30, check=False)
        detail = (result.stdout + result.stderr).strip()
        write_event(action, heard, "ok" if result.returncode == 0 else "error", detail)
        print(detail)
        return result.returncode
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def recognizer(model_path: Path) -> KaldiRecognizer:
    if KaldiRecognizer is None or Model is None or SetLogLevel is None:
        raise RuntimeError(
            "dépendance Vosk absente; exécuter ce service avec "
            "/home/nic/nyxeos_pi5/nyxeos_pi/nyx_env/bin/python"
        )
    if not model_path.exists():
        raise FileNotFoundError(f"modèle Vosk absent: {model_path}")
    SetLogLevel(-1)
    grammar = json.dumps(list(GRAMMAR), ensure_ascii=False)
    return KaldiRecognizer(Model(str(model_path)), SAMPLE_RATE, grammar)


def extract_text(result: str) -> str:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return ""
    return normalize(str(payload.get("text") or payload.get("partial") or ""))


def listen(model_path: Path, once: bool = False, cooldown: float = 5.0) -> int:
    rec = recognizer(model_path)
    source = wake_source()
    process = subprocess.Popen(
        [
            "parec",
            f"--device={source}",
            "--raw",
            "--rate=16000",
            "--channels=1",
            "--format=s16le",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(
        f"Nyxeos écoute « Dis ChatGPT » sur {socket.gethostname()} via {source}",
        flush=True,
    )
    last_activation = 0.0
    last_partial = ""
    last_voice_probe = 0.0
    active_voice = False
    suppress_start_until = 0.0
    try:
        while True:
            if process.stdout is None:
                return 2
            chunk = process.stdout.read(4000)
            if not chunk:
                return 2
            chunk = amplify_pcm16(chunk)
            accepted = rec.AcceptWaveform(chunk)
            text = extract_text(rec.Result() if accepted else rec.PartialResult())
            if text and text != last_partial:
                print(f"Vosk {'final' if accepted else 'partiel'}: {text}", flush=True)
                last_partial = text
            current_time = time.monotonic()
            if current_time - last_voice_probe >= 1.0:
                active_voice = voice_capture_active()
                last_voice_probe = current_time
            if (
                active_voice
                and is_single_utterance_stop(text)
                and current_time - last_activation >= cooldown
            ):
                last_activation = current_time
                suppress_start_until = current_time + POST_STOP_START_GUARD
                print(f"commande vocale continue: {text} -> stop", flush=True)
                dispatch("stop", text)
                if once:
                    return 0
                continue
            action = classify_command(text)
            if action is None or time.monotonic() - last_activation < cooldown:
                continue
            if action == "start" and not should_dispatch_start(text, accepted):
                print("démarrage différé: attente d'une phrase finale complète", flush=True)
                continue
            if action == "start" and current_time < suppress_start_until:
                print("démarrage ignoré: protection post-arrêt active", flush=True)
                continue
            if action == "start" and active_voice:
                print(
                    "ChatGPT déjà actif; attente éventuelle du mot « arrête »",
                    flush=True,
                )
                continue
            last_activation = time.monotonic()
            print(f"commande vocale: {text} -> {action}", flush=True)
            dispatch(action, text)
            if once:
                return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def self_test(model_path: Path) -> int:
    recognizer(model_path)
    checks = {
        "dit chat g p t": classify_command("dit chat g p t"),
        "dit chat g p t arrête": classify_command("dit chat g p t arrête"),
        "bruit quelconque": classify_command("bruit quelconque"),
    }
    result = {
        "model": str(model_path),
        "model_exists": model_path.exists(),
        "controller_exists": CONTROLLER.exists(),
        "parec": subprocess.run(["which", "parec"], capture_output=True).returncode == 0,
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if checks == {
        "dit chat g p t": "start",
        "dit chat g p t arrête": "stop",
        "bruit quelconque": None,
    } else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Wake-word local ChatGPT pour Nyxeos")
    parser.add_argument("--model")
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--trigger", choices=("start", "stop"))
    args = parser.parse_args()
    model_path = active_model_path(args.model)
    if args.self_test:
        return self_test(model_path)
    if args.trigger:
        return int(dispatch(args.trigger, f"manual:{args.trigger}", wait=True))
    if args.listen:
        return listen(model_path, once=args.once)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
