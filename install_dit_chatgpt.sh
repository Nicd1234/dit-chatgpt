#!/bin/sh
set -eu
BUNDLE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${DIT_CHATGPT_PYTHON:-python3}
if ! command -v chromium >/dev/null 2>&1; then
  echo 'Chromium absent: installation via apt...'
  sudo apt-get update
  sudo apt-get install -y chromium wtype
elif ! command -v wtype >/dev/null 2>&1; then
  echo 'wtype absent: installation via apt...'
  sudo apt-get update
  sudo apt-get install -y wtype
fi
command -v pactl >/dev/null || { echo 'PipeWire/pactl absent'; exit 1; }
"$PYTHON" -c 'import vosk, websocket' 2>/dev/null || { echo 'Dépendances Python manquantes: vosk websocket'; exit 1; }
chmod +x "$BUNDLE_ROOT"/scripts/*.sh
mkdir -p "$HOME/.config/systemd/user"
sed -e "s#__BUNDLE_ROOT__#$BUNDLE_ROOT#g" -e "s#__PYTHON__#$PYTHON#g" \
  "$BUNDLE_ROOT/deployment/dit-chatgpt.service.in" > "$HOME/.config/systemd/user/dit-chatgpt.service"
systemctl --user daemon-reload
systemctl --user enable --now dit-chatgpt.service
echo "dit chatgpt installé depuis $BUNDLE_ROOT"
echo "État: systemctl --user status dit-chatgpt.service"
