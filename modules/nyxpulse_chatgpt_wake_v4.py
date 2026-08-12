#!/usr/bin/env python3
"""Déclencheur vocal local Nyxeos v3, durci contre les faux positifs."""

from nyxpulse_chatgpt_wake_v2 import *  # noqa: F403
import math
import os
try:
    from nyx_voiceprint_v1 import verify as verify_voiceprint
except ImportError:
    verify_voiceprint = None


MIN_RAW_RMS = 100.0
MIN_RAW_PEAK = 500
CONTROLLER = Path(__file__).with_name("nyx_chatgpt_voice_controller_v4.py")  # noqa: F405
MODEL_OVERRIDE = os.environ.get("DIT_CHATGPT_MODEL")
VOICEPRINT_PROFILE = Path(os.environ.get("DIT_CHATGPT_VOICEPRINT_PROFILE", Path(__file__).resolve().parents[1] / "logs" / "dit_chatgpt_voiceprint.json"))
VOICEPRINT_THRESHOLD = float(os.environ.get("DIT_CHATGPT_VOICEPRINT_THRESHOLD", "0.78"))


def dispatch(action: str, heard: str, wait: bool = False):
    """Lance explicitement le contrôleur v4 (et non le dispatch v2 importé)."""
    play_cue(action)  # noqa: F405
    command = ["/usr/bin/python3", str(CONTROLLER), action]
    write_event(action, heard, "dispatched")  # noqa: F405
    if wait:
        result = subprocess.run(command, text=True, capture_output=True, timeout=30, check=False)  # noqa: F405
        detail = (result.stdout + result.stderr).strip()
        write_event(action, heard, "ok" if result.returncode == 0 else "error", detail)  # noqa: F405
        print(detail)
        return result.returncode
    return subprocess.Popen(  # noqa: F405
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )


def main_bundle() -> int:
    return main_v3()  # noqa: F405


def pcm16_levels(chunk: bytes) -> tuple[float, int]:
    samples = array.array("h")  # noqa: F405
    samples.frombytes(chunk)
    if sys.byteorder != "little":  # noqa: F405
        samples.byteswap()
    if not samples:
        return 0.0, 0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    peak = max(abs(sample) for sample in samples)
    return rms, peak


def should_dispatch_command(
    text: str,
    accepted: bool,
    utterance_rms: float,
    utterance_peak: int,
) -> bool:
    return (
        accepted
        and "[unk]" not in normalize(text)  # noqa: F405
        and classify_command(text) is not None  # noqa: F405
        and utterance_rms >= MIN_RAW_RMS
        and utterance_peak >= MIN_RAW_PEAK
    )


def self_test(model_path: Path) -> int:
    checks = {
        "dit chat g p t": classify_command("dit chat g p t"),  # noqa: F405
        "dit chat g p t arrête": classify_command("dit chat g p t arrête"),  # noqa: F405
        "bruit quelconque": classify_command("bruit quelconque"),  # noqa: F405
    }
    result = {
        "model": str(model_path),
        "model_exists": model_path.exists(),
        "controller_exists": CONTROLLER.exists(),
        "parec": subprocess.run(["which", "parec"], capture_output=True).returncode == 0,  # noqa: F405
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))  # noqa: F405
    return 0 if result["model_exists"] and result["controller_exists"] else 1


def listen(model_path: Path, once: bool = False, cooldown: float = 5.0) -> int:  # noqa: F405
    rec = recognizer(model_path)  # noqa: F405
    source = wake_source()  # noqa: F405
    process = subprocess.Popen(  # noqa: F405
        ["parec", f"--device={source}", "--raw", "--rate=16000", "--channels=1", "--format=s16le"],
        stdout=subprocess.PIPE,  # noqa: F405
        stderr=subprocess.PIPE,  # noqa: F405
    )
    print(f"Nyxeos v4 écoute « Dis ChatGPT » sur {socket.gethostname()} via {source}", flush=True)  # noqa: F405
    last_activation = 0.0
    last_partial = ""
    last_voice_probe = 0.0
    active_voice = False
    suppress_start_until = 0.0
    utterance_max_rms = 0.0
    utterance_max_peak = 0
    utterance_raw = bytearray()
    try:
        while True:
            if process.stdout is None:
                return 2
            raw_chunk = process.stdout.read(4000)
            if not raw_chunk:
                return 2
            rms, peak = pcm16_levels(raw_chunk)
            utterance_raw.extend(raw_chunk)
            utterance_max_rms = max(utterance_max_rms, rms)
            utterance_max_peak = max(utterance_max_peak, peak)
            accepted = rec.AcceptWaveform(amplify_pcm16(raw_chunk))  # noqa: F405
            text = extract_text(rec.Result() if accepted else rec.PartialResult())  # noqa: F405
            final_rms, final_peak = utterance_max_rms, utterance_max_peak
            final_raw = bytes(utterance_raw)
            if accepted:
                utterance_max_rms = 0.0
                utterance_max_peak = 0
                utterance_raw.clear()
            if text and text != last_partial:
                print(f"Vosk {'final' if accepted else 'partiel'}: {text}", flush=True)
                last_partial = text
            current_time = time.monotonic()  # noqa: F405
            if current_time - last_voice_probe >= 1.0:
                active_voice = voice_capture_active()  # noqa: F405
                last_voice_probe = current_time
            action = classify_command(text)  # noqa: F405
            if action is None or current_time - last_activation < cooldown:
                continue
            if not should_dispatch_command(text, accepted, final_rms, final_peak):
                if accepted:
                    print(f"commande rejetée: validation acoustique/texte rms={final_rms:.1f} pic={final_peak}", flush=True)
                continue
            if action == "start" and VOICEPRINT_PROFILE.exists() and verify_voiceprint is not None:
                try:
                    voice_ok, voice_score = verify_voiceprint(final_raw, VOICEPRINT_PROFILE, VOICEPRINT_THRESHOLD)
                except ValueError:
                    voice_ok, voice_score = False, 0.0
                if not voice_ok:
                    print(f"démarrage rejeté: empreinte vocale insuffisante score={voice_score:.3f}", flush=True)
                    continue
                print(f"empreinte vocale validée score={voice_score:.3f}", flush=True)
            if action == "start" and current_time < suppress_start_until:
                print("démarrage ignoré: protection post-arrêt active", flush=True)
                continue
            if action == "start" and active_voice:
                print("ChatGPT déjà actif; attente éventuelle du mot « arrête »", flush=True)
                continue
            last_activation = current_time
            if action == "stop":
                suppress_start_until = current_time + POST_STOP_START_GUARD  # noqa: F405
            print(f"commande vocale v4: {text} -> {action} (rms={final_rms:.1f}, pic={final_peak})", flush=True)
            dispatch(action, text)  # noqa: F405
            if once:
                return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:  # noqa: F405
            process.kill()


def main_v4() -> int:
    parser = argparse.ArgumentParser(description="Wake-word local ChatGPT v4")  # noqa: F405
    parser.add_argument("--model")
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--trigger", choices=("start", "stop"))
    args = parser.parse_args()
    model_path = active_model_path(args.model)  # noqa: F405
    if args.self_test:
        return self_test(model_path)  # noqa: F405
    if args.trigger:
        return int(dispatch(args.trigger, f"manual:{args.trigger}", wait=True))  # noqa: F405
    if args.listen:
        return listen(model_path, once=args.once)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main_v4())
