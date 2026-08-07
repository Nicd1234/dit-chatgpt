#!/bin/sh
set -eu
BUNDLE_ROOT=${DIT_CHATGPT_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
exec /usr/bin/chromium \
  --load-extension="$BUNDLE_ROOT/extension" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --remote-allow-origins=http://127.0.0.1:9222 \
  "$@"
