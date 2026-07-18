# S.T.E.A.M — Pipeline validé (BigEye benchmarks)

> Mis à jour le 2026-07-18 : ce document décrivait uniquement le mode `person`
> (YOLO) via des arguments CLI (`--loxone`, `--no-udp`...) qui n'existent plus
> dans `apps/rpi/main.py` (aucun `argparse` — tout passe par
> `config/features.yaml`). Voir [ALGORIGRAMME.md](ALGORIGRAMME.md) pour le
> détail des deux modes (`card` et `person`) et [README.md](README.md) pour la
> configuration.

## Config matérielle STYX
- Raspberry Pi 5 8GB — Debian Trixie aarch64
- Pi Camera Module 3 IMX708 CSI
- Venv Python 3.13 avec --system-site-packages

## Perfs pipeline (headless, mesurées — mode `person`)
| Étape          | Avg    | FPS    |
|----------------|--------|--------|
| Picamera2 1280x720 | 9ms | 108 FPS |
| YOLO yolov8n.pt 320px | 55ms | 18 FPS |
| **Pipeline total** | **64ms** | **15.6 FPS** |

> Pas de benchmark équivalent mesuré pour le mode `card` (L1 Canny/contours +
> L2/L3 ORB) — à faire sur STYX (voir issue de validation production).

## Architecture pipeline — mode `person`
```
Picamera2 (1280x720)
    ↓ frame BGR
YOLODetector (imgsz=320, conf=0.5)
    ↓ PersonTracker : présence continue >= person_duration
AudioPlayer (ffplay, non-bloquant)
    ↓
UDPSend → Loxone (STEAM_DETECT_PERSON)
    ↓
WSBridge → monitor WebSocket :8889
```

## Architecture pipeline — mode `card` (défaut STYX)
```
Picamera2 (1280x720)
    ↓ frame BGR
FastDetector (L1, Canny + contours)
    ↓ losange détecté
CardDetector (L2, ORB + homographie RANSAC) → warp 400×400
    ↓
CardRecognizer (L3, ORB vs PLATEST) → card_id confirmé card_consec_frames fois
    ↓ maintenu card_hold_ms
run_actions() → lookup config/rules.yaml
    ↓
UDP Loxone + VideoPlayer (mpv) + AudioPlayer + WSBridge
```

## Lancer
```bash
source .venv/bin/activate
python apps/rpi/main.py
# tous les paramètres (mode, IP Loxone, ports, seuils...) sont dans
# config/features.yaml — pas d'arguments en ligne de commande
```

## Monitor (depuis Salomon)
Ouvrir `monitor/index.html` dans le navigateur (ou `http://<ip_pi>:8890/monitor`
si `enable_rule_api` est actif), entrer l'IP de STYX + port 8889, cliquer
Connecter.
