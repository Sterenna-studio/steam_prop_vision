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
│       ├── card_detector.py         ← L2 ORB par défaut, SIFT/AKAZE optionnels
│       └── card_recognizer.py       ← Identification carte ORB (confirmation)
├── benchmark/                       ← Corpus, configs et rapports vision offline
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

`card_miss_grace_frames` (défaut 5) : pendant le hold, une frame sans
détection valide (L1/L2/L3) ne réinitialise plus tout immédiatement — le
hold survit à quelques frames de bruit caméra isolées. `hold_start` ne
bouge pas pendant ces frames tolérées : la durée de hold reste basée sur
l'horloge murale, pas rallongée artificiellement. Un changement de carte
réel (ID différent reconnu avec confiance), lui, reste traité
immédiatement — cette tolérance ne s'applique qu'à l'absence de détection.

### Mode `person` (`pipeline_mode: "person"`)

```
Boucle IDLE → YOLO détecte joueur → présence continue >= person_duration
            → TRIGGER (audio) → STANDBY idle_after_s → IDLE
```

Indépendant du mode `card` — un seul des deux modes tourne à la fois, sélectionné
par `pipeline_mode`.

La carte/le joueur déclenché exécute les actions définies dans
`config/rules.yaml` (UDP Loxone, audio, vidéo) via `apps/rpi/actions.py`.
`run_actions()` — appelé par la boucle caméra normale — reste
**inconditionnel** : le FSM (IDLE/STANDBY) protège déjà ce chemin contre
tout re-déclenchement rapproché, et lui ajouter le cooldown désynchroniserait
l'état affiché de ce qui se joue réellement (le système resterait en
STANDBY sans rien jouer si le cooldown bloquait silencieusement l'action).

Le `cooldown` par carte (ex: `plate_bougie: cooldown: 8`) protège
spécifiquement le seul chemin qui contourne ce FSM : le trigger manuel
Loxone `STEAM_TRIGGER:<id>` (voir `LOXONE.md`), qui sans lui pouvait rejouer
une action en boucle sans limite. `handle_loxone_command()` appelle
`RuleEngine.try_trigger()` (vérification + marquage atomiques sous un
verrou — protège aussi contre une rafale de plusieurs `STEAM_TRIGGER`
concurrents pour la même carte) avant `run_actions()`.

`min_duration`, en revanche, reste sans effet avec ce point d'appel : il
suppose un appelant qui interroge `should_trigger()` à répétition tant
qu'une carte est vue, alors que `try_trigger()` n'est appelé qu'une seule
fois, au moment où la commande Loxone arrive. `RuleEngine` avertit au
chargement si une règle active a `min_duration > 0`. Le ping informatif
`STEAM_DETECT_<id>` envoyé pour une carte sans règle configurée n'est lui
jamais soumis au cooldown (rien à rejouer).

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
| `card_consec_frames` | `1` | frames consécutives pour démarrer le hold — L2+L3 vérifient déjà géométrie+score, 1 frame suffit |
| `card_miss_grace_frames` | `5` | frames ratées d'affilée tolérées pendant le hold sans tout reset (bruit caméra isolé) |
| `person_duration` | `2.0` | secondes de présence avant déclenchement (mode person) |
| `persist_after_loss` | `5.0` | persistance joueur après disparition (mode person) |
| `card_min_matches` | `12` | keypoints ORB minimum pour valider |
| `card_score_threshold` | `0.20` | score minimum ORB (0.0–1.0) |
| `enable_monitor` | `true` | WebSocket monitor `:8889` |
| `enable_rule_api` | `true` | Rule editor HTTP `:8890` |
| `enable_stream` | `true` | serveur MJPEG + page `/view` `:5050` |
| `enable_watchdog` | `true` | arrêt forcé si la boucle se fige (voir plus bas) |
| `watchdog_timeout_s` | `20.0` | secondes sans activité avant arrêt forcé |
| `mission_id` | `"flux_1"` | identifiant de mission comparé au QR de validation GM |
| `camera_rotation` | `0` | `0`/`90`/`180`/`270` — corrige le montage physique de la caméra |
| `loxone_ip` | `192.168.1.50` | IP de la box Loxone |
| `yolo_model` | `yolov8n.pt` | Modèle YOLO (mode person uniquement) |

> ⚠️ `tools/feature_gui.py` édite actuellement un jeu de clés obsolète
> (`card_first`, `require_person`, `inspect_timeout`, `card_cooldown`) qui
> n'existe plus dans `config/features.yaml` et n'a aucun effet sur le pipeline
> — à corriger avant de le recommander. En attendant, éditer
> `config/features.yaml` directement (texte simple, commenté).

---

## Détection carte — `steamcore/recognition/`

### `card_detector.py` (L2 — ORB par défaut)

Détecte une carte dans la frame **sans contrainte de fond**.  
Utilise ORB par défaut + BFMatcher + homographie RANSAC. SIFT, AKAZE et
MAGSAC sont accessibles explicitement pour benchmark, sans changer STYX.
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
- **Fiabilité** : chaque déclenchement est doublé d'une attente d'ACK + retry
  (`send_event_reliable`), et Loxone peut piloter STYX en retour
  (`STEAM_PING`, `STEAM_RESET`, `STEAM_TRIGGER:<card_id>`) — catalogue
  complet des messages dans [LOXONE.md](LOXONE.md).

---

## WebSocket Monitor — `monitor/ws_bridge.py`

Émet des events JSON en temps réel vers tous les clients connectés.

```
ws://STYX_IP:8889
```

Le tableau d'administration est servi par la Rule API :

- `http://STYX_IP:8890/monitor` — état caméra/pipeline/détecteurs, FPS et commandes ;
- `http://STYX_IP:8890/plates-ui` — templates réellement chargés, ajout,
  archivage réversible et restauration avec rechargement à chaud ;
- `http://STYX_IP:8890/logs-ui` — consultation du log courant et de ses rotations.

Les modifications de plates faites depuis l'interface sont locales à STYX et
peuvent rendre son clone Git non propre. Les suppressions sont déplacées dans
`.runtime/plate_trash/` (gitignored), jamais effacées définitivement.

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
| `templates_reloaded` | Liste et nombre de plates reprises à chaud |

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

## Validation GM — QR de flux/mission

En plus de `plate_ready_check` (auto-test générique), un QR code imprimé permet
de valider **quelle mission** est active sur la machine — utile si plusieurs
installations STYX tournent des missions différentes (`flux_1`, `flux_2`...).

1. Générer un QR contenant `STEAM_FLUX:<mission_id>` (ex. `STEAM_FLUX:flux_1`)
   avec n'importe quel générateur QR — aucun outil dédié dans ce dépôt, le
   contenu textuel suffit.
2. Le montrer à la caméra : si `<mission_id>` correspond à `mission_id` dans
   `config/features.yaml`, bandeau **"STEAM VISION READY — FLUX_X"** sur
   `/view`. Sinon, bandeau **"FLUX INATTENDU"** (attendu vs reçu).
3. Lecture seule : ne modifie jamais la configuration active, quel que soit le
   résultat.

Décodage via `pyzbar`/ZBar (voir [DEPENDENCIES.md](DEPENDENCIES.md) — le
détecteur QR intégré à OpenCV s'est montré peu fiable en test et n'est utilisé
qu'en repli si `pyzbar`/`libzbar0` sont absents).

---

## Robustesse — reprise après crash

| Mécanisme | Portée |
|---|---|
| `Restart=on-failure` (systemd) | Relance le process en 5s s'il meurt (`deploy/steam-vision.service`) |
| Watchdog interne (`enable_watchdog`) | Force l'arrêt (`os._exit`) si la boucle principale ne progresse plus depuis `watchdog_timeout_s` — couvre le cas où le process reste vivant mais figé (ex. appel caméra bloqué), que systemd seul ne détecte pas |
| Nettoyage au boot (`boot_checks`) | Tue les `mpv`/`ffplay` orphelins d'un crash précédent avant de redémarrer, pour éviter qu'une vidéo reste bloquée à l'écran par-dessus la nouvelle instance |

Aucun état de partie (progression, carte en cours de hold) n'est volontairement
préservé entre un crash et le redémarrage — le pipeline repart toujours d'un
état `IDLE` propre et redétecte normalement dès que la caméra répond.

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

### `generate_samples.py` — Augmentations de stress-test historiques

```bash
# Toutes les cartes
python tools/generate_samples.py --all --count 15

# Une carte
python tools/generate_samples.py -i PLATEST/plate_bougie -n 20

# Seed fixe (reproductible)
python tools/generate_samples.py --all --count 15 --seed 42
```

Génère N variations par image source : rotation, perspective, zoom,
luminosité, contraste, flou, bruit, miroir. Une augmentation écrite dans
`PLATEST` devient une référence runtime ; voir
[`docs/TEMPLATE_POLICY.md`](docs/TEMPLATE_POLICY.md) avant utilisation.
Produit une `preview_augmented.jpg` dans chaque dossier.

### `vision_benchmark.py` — Comparaison reproductible A–E

```bash
python tools/vision_benchmark.py --variant all --homography all --report
```

Format du corpus, métriques et protocole terrain :
[`docs/VISION_BENCHMARK.md`](docs/VISION_BENCHMARK.md). Architecture cible :
[`docs/PERCEPTION_BACKENDS.md`](docs/PERCEPTION_BACKENDS.md). Fiducials :
[`docs/FIDUCIAL_MARKERS.md`](docs/FIDUCIAL_MARKERS.md).

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
3. Capturer un corpus terrain séparé dans benchmark/corpus/
4. Tester avec le benchmark reproductible puis le bench interactif :
   python tools/vision_benchmark.py --variant all --homography all --report
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
