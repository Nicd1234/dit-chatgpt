# dit chatgpt — assistant vocal local portable

Commande vocale locale « dit ChatGPT » pour ouvrir et fermer le mode vocal ChatGPT dans Chromium, avec annulation d’écho et fonctionnement portable depuis une clé USB.

Bundle portable de la chaîne « Dis ChatGPT » : écoute Vosk locale, annulation d’écho PipeWire, lancement Chromium Voice et contrôleur CDP.

## Installation

Monter la clé USB, puis exécuter depuis ce dossier :

```sh
DIT_CHATGPT_PYTHON=/chemin/vers/python-avec-vosk ./install_dit_chatgpt.sh
```

Le service utilisateur est créé dans `~/.config/systemd/user/dit-chatgpt.service`. Le dossier de la clé doit rester monté pendant l’utilisation.

Dépendances système : PipeWire/PulseAudio (`pactl`, `parec`, `paplay`), `wtype`, et un Python avec `vosk` et `websocket-client`. Si Chromium n’est pas présent, l’installateur propose son installation automatique via `apt` et `sudo`.

Le modèle français Vosk est inclus dans `model/`. Les noms USB peuvent être forcés avec `DIT_CHATGPT_MICROPHONE` et `DIT_CHATGPT_SPEAKERS`.

## Empreinte vocale d’activation

Après installation, lance :

```sh
DIT_CHATGPT_ROOT="$PWD" ./scripts/enroll_dit_chatgpt_voice.py
```

Dis « dit ChatGPT » cinq fois. L’empreinte reste locale et filtre uniquement les démarrages; la commande d’arrêt ne demande aucune empreinte. Avant cet enregistrement, le filtre est désactivé.

Les originaux Nyxeos ne sont ni déplacés ni remplacés.
