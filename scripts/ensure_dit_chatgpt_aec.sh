#!/bin/sh
set -eu
source_name=dit_chatgpt_vosk_aec
sink_name=dit_chatgpt_vosk_aec_sink
microphone=${DIT_CHATGPT_MICROPHONE:-$(pactl list short sources | awk 'tolower($0) ~ /c-media|usb.*sound/ {print $2; exit}')}
speakers=${DIT_CHATGPT_SPEAKERS:-$(pactl list short sinks | awk 'tolower($0) ~ /generic|usb.*audio/ {print $2; exit}')}
[ -n "$microphone" ] && [ -n "$speakers" ] || { echo 'Microphone/haut-parleur USB introuvable' >&2; exit 1; }
if ! pactl list short sources | awk '{print $2}' | grep -Fxq "$source_name"; then
  pactl load-module module-echo-cancel source_name="$source_name" sink_name="$sink_name" source_master="$microphone" sink_master="$speakers" aec_method=webrtc use_master_format=yes >/dev/null
fi
pactl set-default-sink "$sink_name"
