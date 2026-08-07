#!/usr/bin/env python3
"""Contrôle local du mode vocal ChatGPT dans Chromium."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import websocket


DEBUG_ENDPOINT = "http://127.0.0.1:9222"
CHATGPT_URL = "https://chatgpt.com/"
BUNDLE_ROOT = Path(os.environ.get("DIT_CHATGPT_ROOT", Path(__file__).resolve().parents[1]))
CHROMIUM_LAUNCHER = str(BUNDLE_ROOT / "scripts" / "chromium_voice_fixed_v3.sh")
DRAFT_LOG = BUNDLE_ROOT / "logs" / "chatgpt_voice_preserved_drafts_v3.jsonl"


def chromium_capture_active() -> bool:
    result = subprocess.run(
        ["pactl", "list", "source-outputs"],
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        return False
    blocks = result.stdout.split("Source Output #")
    return any(
        'application.name = "Chromium input"' in block
        and "Corked: no" in block
        and "Mute: no" in block
        for block in blocks
    )


def targets() -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"{DEBUG_ENDPOINT}/json/list", timeout=2) as response:
        return json.load(response)


def chatgpt_target() -> dict[str, Any] | None:
    try:
        available = targets()
    except (OSError, urllib.error.URLError, TimeoutError):
        return None
    return next(
        (
            item
            for item in available
            if item.get("type") == "page" and "chatgpt.com" in str(item.get("url", ""))
        ),
        None,
    )


def launch_chatgpt() -> None:
    subprocess.Popen(
        [CHROMIUM_LAUNCHER, CHATGPT_URL],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_target(timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    target = chatgpt_target()
    if target is None:
        launch_chatgpt()
    while time.monotonic() < deadline:
        target = chatgpt_target()
        if target is not None:
            return target
        time.sleep(0.25)
    raise TimeoutError("onglet ChatGPT inaccessible via DevTools local")


def evaluate(target: dict[str, Any], expression: str) -> Any:
    socket = websocket.create_connection(
        str(target["webSocketDebuggerUrl"]),
        timeout=25,
        origin=DEBUG_ENDPOINT,
    )
    try:
        socket.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                }
            )
        )
        while True:
            message = json.loads(socket.recv())
            if message.get("id") == 1:
                result = message.get("result", {}).get("result", {})
                if "exceptionDetails" in message.get("result", {}):
                    raise RuntimeError(str(message["result"]["exceptionDetails"]))
                return result.get("value")
    finally:
        socket.close()


def keep_tab_active_without_window_focus(target: dict[str, Any]) -> None:
    """Garde l'onglet actif côté Chromium sans déplacer la fenêtre Wayland."""
    socket = websocket.create_connection(
        str(target["webSocketDebuggerUrl"]), timeout=5, origin=DEBUG_ENDPOINT
    )
    try:
        commands = (
            (1, "Page.enable", {}),
            (2, "Page.setWebLifecycleState", {"state": "active"}),
            (3, "Emulation.setFocusEmulationEnabled", {"enabled": True}),
        )
        for identifier, method, params in commands:
            socket.send(json.dumps({"id": identifier, "method": method, "params": params}))
            while True:
                message = json.loads(socket.recv())
                if message.get("id") == identifier:
                    if message.get("error"):
                        raise RuntimeError(f"{method}: {message['error']}")
                    break
    finally:
        socket.close()


def trusted_click_aria(target: dict[str, Any], label: str) -> bool:
    coordinates = evaluate(
        target,
        f"""
(() => {{
  const button = [...document.querySelectorAll("button")].find(item => {{
    if (item.getAttribute("aria-label") !== {json.dumps(label)}) return false;
    const candidate = item.getBoundingClientRect();
    return candidate.width > 0 && candidate.height > 0 &&
      candidate.bottom > 0 && candidate.right > 0 &&
      candidate.top < window.innerHeight && candidate.left < window.innerWidth;
  }});
  if (!button) return null;
  const rect = button.getBoundingClientRect();
  return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
}})()
""",
    )
    if not isinstance(coordinates, dict):
        return False
    socket = websocket.create_connection(
        str(target["webSocketDebuggerUrl"]),
        timeout=5,
        origin=DEBUG_ENDPOINT,
    )
    try:
        for identifier, event_type in ((1, "mouseMoved"), (2, "mousePressed"), (3, "mouseReleased")):
            socket.send(
                json.dumps(
                    {
                        "id": identifier,
                        "method": "Input.dispatchMouseEvent",
                        "params": {
                            "type": event_type,
                            "x": coordinates["x"],
                            "y": coordinates["y"],
                            "button": "left",
                            "clickCount": 1,
                        },
                    }
                )
            )
            try:
                while True:
                    message = json.loads(socket.recv())
                    if message.get("id") == identifier:
                        break
            except websocket.WebSocketTimeoutException:
                if event_type in ("mousePressed", "mouseReleased"):
                    return True
                raise
    finally:
        socket.close()
    return True


def wait_trusted_click_aria(
    target: dict[str, Any], label: str, timeout: float = 5.0
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if trusted_click_aria(target, label):
            return True
        time.sleep(0.25)
    return False


def focus_target_temporarily(target: dict[str, Any]) -> bool:
    """Place Chromium devant; l'appelant restaure le focus après confirmation."""
    already_focused = bool(evaluate(target, "document.hasFocus()"))
    if already_focused:
        return False
    socket = websocket.create_connection(
        str(target["webSocketDebuggerUrl"]), timeout=5, origin=DEBUG_ENDPOINT
    )
    try:
        socket.send(json.dumps({"id": 1, "method": "Page.bringToFront"}))
        while True:
            message = json.loads(socket.recv())
            if message.get("id") == 1:
                break
    finally:
        socket.close()
    return True


def restore_previous_focus() -> None:
    time.sleep(0.75)
    subprocess.run(
        ["wtype", "-M", "alt", "-k", "Tab", "-m", "alt"],
        timeout=3,
        check=False,
    )


def preserve_and_clear_composer(target: dict[str, Any]) -> dict[str, Any]:
    result = evaluate(
        target,
        """
(() => {
  const editor = document.querySelector('[contenteditable="true"][aria-label="Converser avec ChatGPT"]');
  if (!editor) return {ok: true, cleared: false, text: ""};
  const text = (editor.innerText || "").trim();
  if (!text) return {ok: true, cleared: false, text: ""};
  editor.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(editor);
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("delete", false, null);
  editor.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "deleteContentBackward"}));
  return {ok: true, cleared: true, text};
})()
""",
    )
    if isinstance(result, dict) and result.get("cleared") and result.get("text"):
        DRAFT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DRAFT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "url": target.get("url", ""),
                "text": result["text"],
            }, ensure_ascii=False) + "\n")
    return result if isinstance(result, dict) else {"ok": False, "cleared": False}


def switch_work_to_chat(target: dict[str, Any], timeout: float = 5.0) -> bool:
    """La voix Web est exposée dans Chat, pas dans la surface Work."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = evaluate(
            target,
            """
(() => {
  const radios = [...document.querySelectorAll('[role="radio"]')];
  const chat = radios.find(item => (item.innerText || "").trim() === "Chat");
  if (!chat) return "unavailable";
  if (chat.getAttribute("aria-checked") === "true") return "selected";
  chat.click();
  return "clicked";
})()
""",
        )
        if state == "selected":
            return True
        time.sleep(0.25)
    return False


def start_voice(timeout: float = 20.0) -> dict[str, Any]:
    target = wait_for_target(timeout)
    keep_tab_active_without_window_focus(target)
    switch_work_to_chat(target)
    initial_status = status()
    if initial_status.get("voice") == "active":
        return {"ok": True, "state": "already_active"}
    if initial_status.get("voice") == "muted":
        if wait_trusted_click_aria(target, "Activer le microphone", timeout=2):
            activation_deadline = time.monotonic() + 5
            while time.monotonic() < activation_deadline:
                time.sleep(0.5)
                if status().get("voice") == "active":
                    return {"ok": True, "state": "unmuted_trusted_click"}
        stop_voice(timeout=5)
        time.sleep(1)
        target = wait_for_target(timeout)
    preserve_and_clear_composer(target)
    result = evaluate(
        target,
        """
(async () => {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const buttons = [...document.querySelectorAll("button")];
    if (buttons.some(button => button.getAttribute("aria-label") === "Désactiver le microphone")) {
      return {ok: true, state: "already_active"};
    }
    const unmute = buttons.find(button =>
      button.getAttribute("aria-label") === "Activer le microphone"
    );
    if (unmute) {
      unmute.click();
      await new Promise(resolve => setTimeout(resolve, 500));
      const active = [...document.querySelectorAll("button")].some(button =>
        button.getAttribute("aria-label") === "Désactiver le microphone"
      );
      if (active) return {ok: true, state: "unmuted"};
    }
    const start = buttons.find(button =>
      button.getAttribute("aria-label") === "Démarrer le mode vocal"
    );
    if (start) {
      start.click();
      const activationDeadline = Date.now() + 5000;
      while (Date.now() < activationDeadline) {
        await new Promise(resolve => setTimeout(resolve, 250));
        const currentButtons = [...document.querySelectorAll("button")];
        if (currentButtons.some(button =>
          button.getAttribute("aria-label") === "Désactiver le microphone"
        )) {
          return {ok: true, state: "started_active"};
        }
        const activate = currentButtons.find(button =>
          button.getAttribute("aria-label") === "Activer le microphone"
        );
        if (activate) activate.click();
      }
      return {ok: true, state: "started_muted"};
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return {ok: false, state: "start_button_timeout"};
})()
""",
    )
    if not isinstance(result, dict):
        return {"ok": False, "state": "invalid_result"}
    if result.get("state") == "started_muted":
        # Une session vocale doit rester focalisée; le stop restaurera le terminal.
        focus_target_temporarily(target)
        if wait_trusted_click_aria(target, "Activer le microphone", timeout=5):
            activation_deadline = time.monotonic() + 15
            while time.monotonic() < activation_deadline:
                time.sleep(0.5)
                final_status = status()
                if final_status.get("voice") == "active":
                    return {"ok": True, "state": "started_active_trusted_click"}
        activation_deadline = time.monotonic() + 10
        while time.monotonic() < activation_deadline:
            if chromium_capture_active():
                return {"ok": True, "state": "started_active_pipewire_delayed"}
            time.sleep(0.5)
        if chromium_capture_active():
            return {"ok": True, "state": "started_active_pipewire"}
    return result


def stop_voice(timeout: float = 10.0) -> dict[str, Any]:
    target = wait_for_target(timeout)
    restore_focus = focus_target_temporarily(target)
    try:
        clicked = wait_trusted_click_aria(target, "Mettre fin au mode vocal", timeout=3)
        if not clicked and not chromium_capture_active():
            return {"ok": True, "state": "stopped_after_button_disappeared"}
        if not clicked:
            return {"ok": False, "state": "stop_button_click_failed"}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not chromium_capture_active():
                return {"ok": True, "state": "stopped_trusted_click"}
            time.sleep(0.5)
        return {"ok": False, "state": "stop_capture_timeout"}
    finally:
        if restore_focus:
            restore_previous_focus()


def stop_voice_resilient(timeout: float = 10.0) -> dict[str, Any]:
    last_error = ""
    for attempt in range(2):
        try:
            result = stop_voice(timeout)
            if result.get("ok") or not chromium_capture_active():
                return result
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.75)
    if not chromium_capture_active():
        return {"ok": True, "state": "stopped_verified_after_retry"}
    return {"ok": False, "state": "stop_retry_failed", "error": last_error}


def status() -> dict[str, Any]:
    target = chatgpt_target()
    if target is None:
        return {"ok": True, "browser": "unavailable", "voice": "unknown"}
    result = evaluate(
        target,
        """
(() => {
  const labels = [...document.querySelectorAll("button")]
    .map(button => button.getAttribute("aria-label"));
  return {
    ok: true,
    browser: "connected",
    voice: labels.includes("Désactiver le microphone") ? "active" :
      (labels.includes("Mettre fin au mode vocal") ? "muted" : "inactive")
  };
})()
""",
    )
    if isinstance(result, dict):
        if result.get("voice") == "muted" and chromium_capture_active():
            result["voice"] = "active"
            result["verified_by"] = "pipewire"
        return result
    return {"ok": False, "voice": "invalid_result"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Contrôleur local du mode vocal ChatGPT")
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    try:
        if args.action == "start":
            result = start_voice(args.timeout)
        elif args.action == "stop":
            result = stop_voice_resilient(args.timeout)
        else:
            result = status()
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "action": args.action}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
