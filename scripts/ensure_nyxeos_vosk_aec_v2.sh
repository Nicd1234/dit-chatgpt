#!/bin/sh
set -eu

aec_source="nyxeos_vosk_aec"
aec_sink="nyxeos_vosk_aec_sink"
microphone="alsa_input.usb-C-Media_Electronics_Inc._USB_PnP_Sound_Device-00.analog-mono"
speakers="alsa_output.usb-Generic_USB2.0_Device_20121120222016-00.analog-stereo"

if ! pactl list short sources | awk '{print $2}' | grep -Fxq "$aec_source"; then
  pactl load-module module-echo-cancel \
    source_name="$aec_source" \
    sink_name="$aec_sink" \
    source_master="$microphone" \
    sink_master="$speakers" \
    aec_method=webrtc \
    use_master_format=yes >/dev/null
fi

pactl set-default-sink "$aec_sink"
