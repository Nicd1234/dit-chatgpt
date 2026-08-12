#!/usr/bin/env python3
"""Enregistre 5 phrases « dit ChatGPT » pour le filtre d’activation."""
from __future__ import annotations
import os
import subprocess
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules"))
from nyx_voiceprint_v1 import enroll

ROOT = Path(os.environ.get("DIT_CHATGPT_ROOT", Path(__file__).resolve().parents[1]))
PROFILE = Path(os.environ.get("DIT_CHATGPT_VOICEPRINT_PROFILE", ROOT / "logs" / "dit_chatgpt_voiceprint.json"))

samples = []
for index in range(5):
    input(f"Échantillon {index + 1}/5 — appuie sur Entrée puis dis « dit ChatGPT » : ")
    process = subprocess.Popen(["parec", "--device=nyxeos_vosk_aec", "--raw", "--rate=16000", "--channels=1", "--format=s16le"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        samples.append(process.stdout.read(32000))
    finally:
        process.terminate()
print(json.dumps(enroll(samples, PROFILE), ensure_ascii=False))
print(f"Empreinte enregistrée: {PROFILE}")
