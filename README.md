# S.T.E.A.M Vision

> Système de reconnaissance de cartes/plaques pour salle d'escape game — Raspberry Pi 5 + IMX708

**Stack** : Python 3.13 · Picamera2 · OpenCV · YOLO (Ultralytics) · WebSockets · UDP/Loxone

---

## Architecture du projet

```
steam_prop_vision/
├── apps/
│   └── rpi/
│       └── main.py                  ← Pipeline principale (prod)
├── steamcore/
│   ├── detector.py                  ← Détection joueur YOLO
│   ├── person_tracker.py            ← Gestion état joueur (presence/persistance/mouvement)
│   └── recognition/
│       ├── card_detector.py         ← Détection carte SIFT + homographie (v2, fond-indépendant)
│       └── card_recognizer.py       ← Identification carte ORB (confirmation)
├── monitor/
│   └── ws_bridge.py                 ← WebSocket monitor (ws://STYX:8889)
├── config/
│   ├── features.yaml                ← Tous les paramètres de la pipeline
│   └── rules.yaml                   ← Règles de déclenchement par carte
├── PLATEST/
│   ├── plate_bougie/                ← Images templates de la plaque bougie
│   ├── plate_cellule/
│   ├── plate_chaudron/
│   ├── plate_dague/
│   └── plate_vampire/
├── assets/
│   ├── audio/                       ← Sons déclenchés par carte
│   └── video/                       ← Vidéos déclenchées par carte
├── tools/
│   ├── pipeline_test.py             ← Dev/calibration interactif avec preview cam
│   ├── plate_bench.py               ← Bench de validation des cartes (terminal + preview)
│   ├── plate_bench_gui.py           ← Bench GUI complet (preview + scores + historique)
│   ├── generate_samples.py          ← Générateur d'augmentation PLATEST
│   └── feature_gui.py               ← Interface graphique pour éditer features.yaml
└── scripts/
    └── linux_run.sh                 ← Script de lancement (alias run_vision)
```

---

## Lancement rapide

```bash
# Production (depuis STYX)
run_vision

# Équivalent long
bash scripts/linux_run.sh --loxone 192.168.1.50

# Sans monitor WebSocket
bash scripts/linux_run.sh --loxone 192.168.1.50 --no-monitor
```

---

## Pipeline principale — `apps/rpi/main.py`

Machine à états : `IDLE ⇄ STANDBY` (2 états seulement — pas d'état `INSPECTION`/
`TRIGGERED`, contrairement à des versions antérieures du projet).

### Mode `card` (`pipeline_mode: "card"`, défaut STYX)

```
Boucle IDLE → Scan carte L1(FastDetector)→L2(CardDetector)→L3(CardRecognizer)
            → même carte confirmée card_consec_frames images consécutives
            → maintenue card_hold_ms → TRIGGER (actions rules.yaml)
            → STANDBY jusqu'à fin vidéo + idle_after_s → IDLE
```

Pas de vérification de présence joueur (YOLO) dans ce mode — uniquement piloté
par la détection de carte.

### Mode `person` (`pipeline_mode: "person"`)

```
Boucle IDLE → YOLO détecte joueur → présence continue >= person_duration
            → TRIGGER (audio) → STANDBY idle_after_s → IDLE
```

Indépendant du mode `card` — un seul des deux modes tourne à la fois, sélectionné
par `pipeline_mode`.

La carte/le joueur déclenché exécute les actions définies dans
`config/rules.yaml` (UDP Loxone, audio, vidéo). Le `cooldown` et `min_duration`
définissables par carte dans `rules.yaml` sont validés au chargement mais **ne
sont pas actuellement appliqués** par `apps/rpi/main.py` — l'anti-répétition en
production passe uniquement par `idle_after_s` (délai global, pas par carte).

---

## Configuration — `config/features.yaml`

Tous les paramètres sont modifiables ici **sans toucher au code**. Liste
complète et à jour dans le fichier lui-même (commenté) ; principaux
paramètres :

| Paramètre | Défaut | Description |
|---|---|---|
| `pipeline_mode` | `"card"` | `"card"` ou `"person"` |
| `card_hold_ms` | `1000` | ms de maintien de la carte avant déclenchement |
| `idle_after_s` | `3.0` | secondes avant retour en IDLE après trigger |
| `card_consec_frames` | `5` | frames consécutives pour confirmer la carte |
| `person_duration` | `2.0` | secondes de présence avant déclenchement (mode person) |
| `persist_after_loss` | `5.0` | persistance joueur après disparition (mode person) |
| `card_min_matches` | `12` | keypoints ORB minimum pour valider |
| `card_score_threshold` | `0.20` | score minimum ORB (0.0–1.0) |
| `enable_monitor` | `true` | WebSocket monitor `:8889` |
| `enable_rule_api` | `true` | Rule editor HTTP `:8890` |
| `enable_stream` | `true` | serveur MJPEG + page `/view` `:5050` |
| `loxone_ip` | `192.168.1.50` | IP de la box Loxone |
| `yolo_model` | `yolov8n.pt` | Modèle YOLO (mode person uniquement) |

> ⚠️ `tools/feature_gui.py` édite actuellement un jeu de clés obsolète
> (`card_first`, `require_person`, `inspect_timeout`, `card_cooldown`) qui
> n'existe plus dans `config/features.yaml` et n'a aucun effet sur le pipeline
> — à corriger avant de le recommander. En attendant, éditer
> `config/features.yaml` directement (texte simple, commenté).

---

## Détection carte — `steamcore/recognition/`

### `card_detector.py` (v2 — SIFT)

Détecte une carte dans la frame **sans contrainte de fond**.  
Utilise SIFT + matching BFMatcher + homographie RANSAC.  
→ Fonctionne sur fond variable (t-shirt joueur, table, etc.)

```python
detector = CardDetector(platest_dir="PLATEST")
region   = detector.detect(frame)
# region.warped   : patch 400×400 normalisé
# region.corners  : 4 coins dans la frame
```

### `card_recognizer.py` (v2 — ORB)

Second passage de confirmation sur le warp 400×400.

```python
recognizer = CardRecognizer("PLATEST", min_matches=8, threshold=0.04)
result     = recognizer.recognize(region.warped)
# result.card_id, result.label, result.score, result.matches
```

---

## Détection joueur — `steamcore/`

### `detector.py` — YOLODetector

```python
detector   = YOLODetector(model_path="yolov8n.pt")
pf         = detector.detect_persons(frame)
# pf.count     : nb joueurs dans la frame
# pf.centroid  : (x, y) du joueur principal
# pf.bbox      : (x1, y1, x2, y2)
```

### `person_tracker.py` — PersonTracker

Gère la logique temporelle de présence joueur.

```python
tracker = PersonTracker(person_duration=2.0, persist_after_loss=5.0)
state   = tracker.update(person_frame)
# state.ready_for_inspect   : True si joueur présent >= 2s
# state.person_state        : ABSENT / PRESENT / PERSISTING
# state.movement.direction  : "gauche" / "droite" / "haut" / "bas" / "statique"
# state.person_count        : nb joueurs actuels
```

---

## Communication UDP — `steamcore/udp.py`

```python
send_event("STEAM_CARD_BOUGIE", loxone_ip, loxone_port)
```

- **Heartbeat** : `STEAM_RUN_OK` toutes les 5s (désactivable via `enable_heartbeat`)
- **Écoute** : port 8888 pour recevoir des commandes depuis Loxone

---

## WebSocket Monitor — `monitor/ws_bridge.py`

Émet des events JSON en temps réel vers tous les clients connectés.

```
ws://STYX_IP:8889
```

Events émis :

| type | Contenu |
|---|---|
| `state` | `IDLE / STANDBY` |
| `card_detected` | `card_id, label, score` |
| `system_ready` | `label` — auto-test GM (carte `plate_ready_check`), affiché sur `/view` |
| `count` | Nombre de joueurs |
| `movement` | `direction, dx, dy, speed` |
| `udp_sent` | Message envoyé à Loxone |
| `status` | Message texte libre |

---

## PLATEST — Templates de reconnaissance

Chaque sous-dossier = une carte. Mettre **minimum 2-3 images** par carte,
idéalement **10-15** en conditions réelles (éclairage salle, angles variés).

> `plate_ready_check` est un identifiant **réservé** : la montrer à la caméra
> affiche un bandeau "STEAM VISION READY" sur `/view` pendant quelques
> secondes (confirme caméra → L1 → L2 → L3 → WebSocket), **sans** déclencher
> UDP Loxone, vidéo ni audio — utile aux GM pour un auto-test rapide avant une
> session. Ne pas réutiliser cet `card_id` pour une vraie plaque de jeu.

```
PLATEST/
└── plate_bougie/
    ├── source.jpg          ← image source originale
    ├── sample_1234.jpg     ← photo réelle prise avec touche A du bench
    ├── aug_source_001.jpg  ← augmentation générée automatiquement
    └── preview_augmented.jpg  ← contact sheet de preview
```

---

## Outils — `tools/`

### `pipeline_test.py` — Test interactif

```bash
python tools/pipeline_test.py [--pi]
```

Au lancement : choix mode (RUN / DEV / CALIBRATION) + source caméra.

| Mode | Description |
|---|---|
| `RUN` | Lance la pipeline normale |
| `DEV` | Preview cam + overlay losange + scores ORB live + warp |
| `CALIBRATION` | Ajuste `card_min_matches` et `card_score_threshold` |

Touches : `Q` quitter · `R` reload templates · `S` snapshot

---

### `plate_bench.py` — Bench de validation

```bash
python tools/plate_bench.py --pi [--report]
```

Valide chaque carte une par une. Preview cam + overlay + scores ORB en temps réel.

Touches :
- `1`-`5` : changer la carte attendue
- `ESPACE` : capturer et tester
- `A` : sauvegarder le warp dans PLATEST (enrichit les templates)
- `R` : recharger les templates
- `Q` : quitter + rapport final

---

### `plate_bench_gui.py` — Bench GUI complet

```bash
python tools/plate_bench_gui.py --pi [--report]
```

Version avec panneau droite affichant scores ORB, historique session
et résultat du dernier test en temps réel.

---

### `generate_samples.py` — Augmentation PLATEST

```bash
# Toutes les cartes
python tools/generate_samples.py --all --count 15

# Une carte
python tools/generate_samples.py -i PLATEST/plate_bougie -n 20

# Seed fixe (reproductible)
python tools/generate_samples.py --all --count 15 --seed 42
```

Génère N variations par image source : rotation, perspective, zoom,
luminosité, contraste, flou, bruit, miroir.
Produit une `preview_augmented.jpg` dans chaque dossier.

---

### `feature_gui.py` — Interface paramètres

```bash
python tools/feature_gui.py [--config config/features.yaml]
```

GUI Tkinter (sans dépendance externe) pour modifier tous les paramètres
de `features.yaml` par onglets thématiques.

---

## Workflow recommandé — Mise en production

```
1. Fabriquer les plaques (Mecpow laser)
2. Photographier chaque plaque (10-15 photos, angles variés)
   → Copier dans PLATEST/plate_xxx/
3. Générer les augmentations :
   python tools/generate_samples.py --all --count 15
4. Tester avec le bench :
   python tools/plate_bench.py --pi
   → Touche A pour sauvegarder les bons warps
   → Touche R pour recharger
5. Calibrer les seuils si besoin :
   python tools/pipeline_test.py --pi  (mode CALIBRATION)
6. Lancer en production :
   run_vision
```

---

## Dépendances principales

```
picamera2
opencv-contrib-python   ← IMPORTANT : pas opencv-python seul (besoin de SIFT)
ultralytics             ← YOLO
pyyaml
websockets
```

Vérifier SIFT disponible :
```bash
python -c "import cv2; cv2.SIFT_create(); print('SIFT OK')"
```

---

## Machines

| Machine | Rôle |
|---|---|
| **STYX** (Pi 5) | Exécution pipeline, caméra IMX708 |
| **Salomon** (Windows 11) | Développement, outils, GitHub |
| **Loxone** | Réception UDP, déclenchement effets salle |
