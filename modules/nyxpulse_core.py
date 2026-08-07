#!/usr/bin/env python3
"""Coeur logique NyxPulse.

Transforme un pulse court en intention locale a partir d'un dictionnaire
versionne. Ce module ne lance aucune commande systeme: il simule et journalise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
LOCAL_DICTIONARY = BASE_DIR / "references" / "nyxpulse_dictionary_v1.json"
NAS_DICTIONARY = Path("/mnt/nyxeos_nas/dictionaries/nyxpulse_dictionary_v1.json")
SERVER_DICTIONARY = Path("/srv/nyxeos/dictionaries/nyxpulse_dictionary_v1.json")
LOCAL_LOG = BASE_DIR / "journal" / "nyxpulse_events.jsonl"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def active_dictionary_path(path: str | None = None) -> Path:
    if path:
        return Path(path)
    for candidate in (NAS_DICTIONARY, SERVER_DICTIONARY, LOCAL_DICTIONARY):
        if candidate.exists():
            return candidate
    return LOCAL_DICTIONARY


def load_dictionary(path: str | None = None) -> dict[str, Any]:
    target = active_dictionary_path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    if "entries" not in data or not isinstance(data["entries"], dict):
        raise ValueError(f"dictionnaire invalide: {target}")
    data["_path"] = str(target)
    data["_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return data


def normalize_pulse(pulse: str) -> str:
    cleaned = "".join(ch for ch in pulse.upper().strip() if ch.isalnum())
    if not cleaned:
        raise ValueError("pulse vide")
    if len(cleaned) > 16:
        raise ValueError("pulse trop long")
    return cleaned


def decode_pulse(pulse: str, dictionary_path: str | None = None) -> dict[str, Any]:
    dictionary = load_dictionary(dictionary_path)
    normalized = normalize_pulse(pulse)
    entry = dictionary["entries"].get(normalized)
    result = {
        "timestamp": now(),
        "host": socket.gethostname(),
        "pulse": normalized,
        "dictionary": {
            "name": dictionary.get("name"),
            "version": dictionary.get("version"),
            "path": dictionary.get("_path"),
            "sha256": dictionary.get("_sha256"),
        },
        "known": entry is not None,
        "entry": entry,
        "execution_mode": "simulation",
    }
    if entry is None:
        result["status"] = "unknown_pulse"
        result["simulation_plan"] = []
    else:
        result["status"] = "decoded"
        result["simulation_plan"] = entry.get("simulation", [])
    return result


def encode_name(name: str, dictionary_path: str | None = None) -> dict[str, Any]:
    dictionary = load_dictionary(dictionary_path)
    wanted = name.lower().strip()
    for pulse, entry in dictionary["entries"].items():
        if entry.get("name", "").lower() == wanted:
            return {"name": name, "pulse": pulse, "entry": entry}
    raise KeyError(f"nom absent du dictionnaire: {name}")


def write_event(event: dict[str, Any]) -> None:
    targets = [
        Path("/mnt/nyxeos_nas/logs/nyxpulse_events.jsonl"),
        Path("/srv/nyxeos/logs/nyxpulse_events.jsonl"),
        LOCAL_LOG,
    ]
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            return
        except OSError:
            continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Encodeur/decodeur logique NyxPulse")
    parser.add_argument("--dictionary", help="chemin du dictionnaire")
    parser.add_argument("--decode", help="pulse a decoder")
    parser.add_argument("--encode-name", help="nom d'entree a encoder")
    parser.add_argument("--log", action="store_true", help="journaliser le resultat")
    args = parser.parse_args()

    if args.decode:
        result = decode_pulse(args.decode, args.dictionary)
    elif args.encode_name:
        result = encode_name(args.encode_name, args.dictionary)
    else:
        result = {
            "dictionary": load_dictionary(args.dictionary),
            "message": "utilise --decode PULSE ou --encode-name NOM",
        }
    if args.log:
        write_event(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
