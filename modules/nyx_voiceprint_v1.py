#!/usr/bin/env python3
"""Empreinte acoustique locale légère pour valider uniquement les démarrages."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

SAMPLE_RATE = 16000
PROFILE_VERSION = 1


def voiceprint_from_pcm16(raw: bytes) -> list[float]:
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if samples.size < SAMPLE_RATE // 2:
        raise ValueError("échantillon vocal trop court")
    samples /= max(1.0, float(np.max(np.abs(samples))))
    frame = int(SAMPLE_RATE * 0.025)
    hop = int(SAMPLE_RATE * 0.010)
    window = np.hanning(frame).astype(np.float32)
    features = []
    for start in range(0, samples.size - frame, hop):
        spectrum = np.abs(np.fft.rfft(samples[start:start + frame] * window))
        bins = spectrum[2:81]
        energy = float(np.sum(bins))
        if energy < 1e-5:
            continue
        bins = np.log1p(bins / energy)
        features.append(bins)
    if len(features) < 8:
        raise ValueError("voix insuffisante dans l’échantillon")
    matrix = np.asarray(features, dtype=np.float32)
    vector = np.concatenate([matrix.mean(axis=0), matrix.std(axis=0)])
    vector /= max(1e-8, float(np.linalg.norm(vector)))
    return [round(float(value), 8) for value in vector]


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    a = np.asarray(list(left), dtype=np.float32)
    b = np.asarray(list(right), dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if denominator == 0 else float(np.dot(a, b) / denominator)


def enroll(samples: Iterable[bytes], profile_path: Path) -> dict:
    vectors = [voiceprint_from_pcm16(sample) for sample in samples]
    vector = np.asarray(vectors, dtype=np.float32).mean(axis=0)
    vector /= max(1e-8, float(np.linalg.norm(vector)))
    profile = {"version": PROFILE_VERSION, "sample_count": len(vectors), "vector": [round(float(x), 8) for x in vector]}
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return profile


def verify(raw: bytes, profile_path: Path, threshold: float = 0.78) -> tuple[bool, float]:
    if not profile_path.exists():
        return True, 1.0
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    score = cosine_similarity(voiceprint_from_pcm16(raw), profile["vector"])
    return score >= threshold, score
