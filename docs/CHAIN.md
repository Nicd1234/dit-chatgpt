# Chaîne dit chatgpt

`nyxpulse_chatgpt_wake_v4.py` → `nyx_chatgpt_voice_controller_v4.py` → Chromium DevTools Protocol → ChatGPT.com Voice.

Le service utilise `ensure_dit_chatgpt_aec.sh` avant l’écoute. Le contrôleur v4 garde Chromium focalisé pendant la session, puis rend le focus après l’arrêt confirmé.

`nyx_voiceprint_v1.py` peut valider l’empreinte locale avant `start`. Il n’est jamais consulté pour `stop`.
