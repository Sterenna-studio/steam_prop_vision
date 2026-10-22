# AUDIT — S.T.E.A.M Vision · Mai 2026

> Branche dédiée : `audit/may-2026`  
> Auteur audit : Perplexity AI (assistant Pierre H.)  
> Date : 17 mai 2026

---

## Mise à jour — octobre 2026 (état vérifié dans le code)

Cet audit de mai 2026 a été relu contre le code actuel. Les sections suivantes
restent l'historique d'origine ; cette section fait foi en cas de désaccord.
Suivi des améliorations de performance et de fiabilité : issue #10.

### Corrigé depuis l'audit
- `main.py` : try/except global avec log (`CRASH NON GÉRÉ`), logs rotatifs,
  watchdog anti-freeze (`apps/rpi/watchdog.py`), service systemd
  (`deploy/steam-vision.service`).
- Repo : `yolov8n.pt` (désormais ignoré via `*.pt`), `WantedRH.jpg`, `refacto/`,
  `configtest/`, `app_flask.py` et `plate_bench_gui.py` ont disparu ; plate
  `bois` versionnée ; tag `v2.1.0` ; `.gitattributes` présent.
- `rules.yaml` : validation de schéma (`validate_rules_schema`).
- Tests : couverture bien au-delà de `card_recognizer`/`rules` (160+ tests,
  CI ruff + pytest).
- L2 tourne en **ORB par défaut** ; SIFT/AKAZE mesurés trop lents (jusqu'à
  2,4 s/frame) sans gain de recall : écartés (`docs/VISION_BENCHMARK.md`).

### Erreur de l'audit initial
- « Matching sur 4 quadrants : bonne stratégie anti-occlusion » : **faux**.
  `card_recognizer.py` faisait un matching global avec
  `score = bons_matchs / max(points_template, points_requête)` : les points
  parasites d'un doigt gonflent le dénominateur et font tomber le score (cas
  terrain : un petit morceau de doigt sur l'illustration empêchait la
  détection). Modes `template` et `zones` ajoutés (`scoring.py`, défaut
  `global`, à valider au benchmark avant activation).

### Constats vérifiés (mesures STYX, `docs/VISION_BENCHMARK.md`)
- ~124 ms p50 par frame en ORB/ORB (≈ 8 fps) ; MAGSAC plus stable que RANSAC.
- L1 hit : 78 % en frontal, **10 % avec un doigt sur le bord** (le contour
  est le maillon faible, pas L3). Repli plein cadre : 86,7 % de triggers
  corrects contre 33,3 % pour le contour seul — un seul opérateur, une seule
  distance, 20 frames négatives : indicatif, pas une validation.

### Livré pour l'issue #10 (tout désactivé par défaut, production inchangée)
- Porte de mouvement (`apps/rpi/motion_gate.py`) : pas de QR/L1/L2/L3 sur une
  scène figée.
- Score L3 tolérant à l'occlusion (`steamcore/recognition/scoring.py`),
  sélectionnable via `recognition.score_mode` et `--score-mode` au benchmark.
- Repli plein cadre borné (`apps/rpi/fullframe_fallback.py`).
- Snapshots de diagnostic par type (validée, L1/L2/L3) et page `/snapshots`.

### Reste ouvert
- 🔴 Mesurer sur STYX (latence, CPU à vide, recall avec doigt, faux positifs)
  avant d'activer quoi que ce soit ; corpus de négatifs difficiles (#9).
- 🟡 `video_player.py` : pas de timeout sur le socket IPC mpv, pas de
  vérification de la présence de `mpv` au démarrage (le nettoyage des mpv
  orphelins existe dans `boot.py`, pas le contrôle d'installation).
- 🟡 `udp.py` : pas de retry sur échec d'envoi (le port d'écoute est déjà
  configurable via `udp_listen_port`, contrairement à ce que disait l'audit).
- 🟡 `apps/rpi/main_gui.py` duplique `run_actions()` (voir AGENTS.md).
- 🟡 `tools/feature_gui.py` édite des clés obsolètes.
- 🟡 `requirements_rpi.lock.txt` à générer après validation (#7) ; vidéos
  placeholder à remplacer (droit d'auteur) ; historique git alourdi.

---

## 1. Vue d'ensemble

| Critère | État | Note |
|---|---|---|
| Structure projet | ✅ Bonne | Modules bien séparés |
| Qualité du code | ⚠️ Correcte | Quelques points à améliorer |
| Documentation | ✅ Bonne | README + ALGORIGRAMME présents |
| Sécurité / Robustesse | ⚠️ Moyenne | Pas de gestion d'erreur réseau |
| Performance RPi | ⚠️ À surveiller | SIFT + YOLO sur Pi 5, pas de benchmark récent |
| Maintenabilité | ⚠️ Correcte | Dossiers reliquats à nettoyer |
| Git hygiene | ⚠️ Passable | Commits vagues, binaire dans le repo |

---

## 2. Structure du projet

### ✅ Points positifs
- Architecture modulaire claire : `steamcore/` bien découpé par responsabilité
- Pipeline en 3 niveaux (L1 FastDetector → L2 CardDetector → L3 CardRecognizer) bien documentée
- Double requirements (`requirements.txt` + `requirements_rpi.txt`) : bonne pratique
- `config/features.yaml` centralisé — aucun hardcode dans le code métier
- `rules.yaml` séparé du code — bon découplage logique métier / config

### ⚠️ Points à corriger

| Problème | Fichier / Dossier | Priorité |
|---|---|---|
| `yolov8n.pt` (6.5 MB) commité directement | `/yolov8n.pt` | 🔴 Haute |
| `WantedRH.jpg` (705 KB) dans la racine | `/WantedRH.jpg` | 🟡 Moyenne |
| Dossier `refacto/` probablement obsolète | `/refacto/` | 🟡 Moyenne |
| Dossier `configtest/` probablement obsolète | `/configtest/` | 🟡 Moyenne |
| `app_flask.py` en racine sans dossier dédié | `/app_flask.py` | 🟢 Faible |
| `udp_test.py` en racine (outil de dev) | `/udp_test.py` | 🟢 Faible |

---

## 3. Audit code — `steamcore/`

### `steamcore/recognition/pipeline.py` — Pipeline L1→L2→L3
- ✅ Logique claire, niveaux bien séparés
- ⚠️ Pas de timeout configurable par niveau — si L2 SIFT freeze, tout bloque
- ⚠️ Pas de logging structuré (print() vs logger Python)

### `steamcore/recognition/card_detector.py` — SIFT
- ✅ BFMatcher + homographie RANSAC : approche solide
- ⚠️ `cv2.SIFT_create()` appelé à chaque instanciation — à mettre en singleton ou cache
- ⚠️ Pas de vérification si `opencv-contrib` est bien installé (SIFT non-libre en opencv standard)

### `steamcore/recognition/card_recognizer.py` — ORB
- ✅ Matching sur 4 quadrants : bonne stratégie anti-occlusion
- ⚠️ Score moyen sur les 4 quadrants : un quadrant totalement absent peut noyer le score — envisager un `max` ou `weighted` plutôt que `mean`

### `steamcore/recognition/fast_detector.py` — L1
- ✅ Pré-filtre rapide avant SIFT : bonne pratique pour la perf RPi
- ⚠️ Si le losange est partiellement occulté, risque de faux négatifs en L1 qui bloquent toute la pipeline

### `steamcore/audio.py`
- ✅ Race condition `proc.wait()` corrigée (commit faba860)
- ⚠️ Pas de fallback si `aplay` / lecteur audio absent sur le système
- ⚠️ Pas de limite sur le nombre de processus audio simultanés

### `steamcore/video_player.py` — mpv IPC
- ✅ OpenCV rapatrié dans le thread principal via `tick()` (commit e9f5d57) — crash corrigé
- ⚠️ Pas de vérification que `mpv` est installé au démarrage
- ⚠️ Timeout IPC socket non configuré — si mpv ne répond pas, le thread peut bloquer
- ⚠️ Pas de reconnexion automatique si le socket IPC mpv tombe

### `steamcore/udp.py`
- ✅ Heartbeat `STEAM_RUN_OK` toutes les 5s : bonne pratique
- ⚠️ Pas de retry sur échec envoi UDP
- ⚠️ Port hardcodé à 8888 — devrait être dans `features.yaml`

### `steamcore/rules.py`
- ✅ Correction `now = now or time.time()` présente (falsy sur 0.0)
- ⚠️ Pas de validation du schéma `rules.yaml` au chargement — une clé manquante peut crasher silencieusement

### `steamcore/person_tracker.py`
- ✅ Logique `ABSENT / PRESENT / PERSISTING` claire
- ⚠️ Tracking multi-joueurs basique — si 2 joueurs, `centroid` est celui du premier bbox uniquement

---

## 4. Audit code — `apps/` et `tools/`

### `apps/rpi/main.py`
- ✅ Pipeline branchée L1→L2→L3 (commit faba860)
- ⚠️ Gestion des exceptions globale absente — une exception non catchée tue le processus sans log
- ⚠️ Pas de watchdog / relance automatique en cas de crash
- 🔴 **Recommandation** : wrapper le `main()` dans un `try/except` global avec log vers fichier

### `tools/`
- ✅ Outils bien séparés du code prod
- ⚠️ `plate_bench_gui.py` et `plate_bench.py` font doublon — à terme, unifier ou supprimer l'ancien

---

## 5. Git hygiene

| Problème | Impact | Action |
|---|---|---|
| `yolov8n.pt` dans le repo (6.5 MB) | Repo lourd, clone lent | Migrer vers Git LFS ou téléchargement automatique |
| `WantedRH.jpg` en racine | Inutile en prod | Déplacer dans `tools/` ou supprimer |
| Commits `add` / `ameiloration` | Historique illisible | Convention : `feat:` / `fix:` / `docs:` |
| Pas de `.gitattributes` pour LFS | — | À configurer si LFS adopté |
| Pas de tag de version | Impossible de savoir quelle version tourne sur STYX | Créer un tag `v1.0.0` sur l'état actuel stable |

---

## 6. Sécurité & robustesse

| Risque | Détail | Recommandation |
|---|---|---|
| Crash silencieux main.py | Exception non catchée = processus mort | `try/except` global + log fichier |
| mpv absent au démarrage | `video_player.py` échoue sans message clair | Check `shutil.which('mpv')` au boot |
| Socket IPC mpv sans timeout | Thread potentiellement bloqué indéfiniment | `socket.settimeout(2.0)` |
| rules.yaml mal formé | Crash à la lecture sans message explicite | Validation schéma avec `pydantic` ou `cerberus` |
| UDP sans ACK | Perte de message silencieuse | Acceptable pour escape game, documenter explicitement |
| Pas de systemd service | Pas de relance auto après crash ou reboot | Créer `steam-vision.service` |

---

## 7. Performance RPi 5

| Composant | Charge estimée | Remarque |
|---|---|---|
| YOLO yolov8n | Modérée | Modèle nano, Pi 5 tient |
| SIFT L2 (toute la frame) | Élevée | Potentiel bottleneck à fort FPS |
| ORB L3 (warp 400×400) | Faible | OK |
| mpv vidéo plein écran | Modérée | GPU RPi5 gère le H264 |
| WebSocket monitor | Faible | OK |

**Recommandation** : limiter le FPS de traitement à 10-15 FPS max via `time.sleep()` ou
`cap.set(cv2.CAP_PROP_FPS, 15)` pour économiser la charge CPU et garder de la marge thermique.

---

## 8. Ce qui manque

- [ ] **Systemd service** `steam-vision.service` pour relance auto
- [ ] **Log fichier** rotatif (`logging.handlers.RotatingFileHandler`)
- [ ] **Watchdog** interne (heartbeat interne + relance si freeze)
- [ ] **Tests unitaires** sur `card_recognizer.py` et `rules.py` (même basiques)
- [ ] **Tag git `v1.0.0`** sur l'état stable actuel
- [ ] **Plate `bois`** : templates présents sur STYX mais pas dans le repo
- [ ] **Git LFS** pour `yolov8n.pt`

---

## 9. Priorités recommandées

### 🔴 Court terme (avant prochaine session escape)
1. Wrapper `main.py` dans un `try/except` global avec log fichier
2. Vérifier `mpv` présent au boot (`shutil.which`)
3. Créer `steam-vision.service` (systemd)
4. Pusher la plate `bois` dans le repo

### 🟡 Moyen terme
5. Migrer `yolov8n.pt` hors du repo (Git LFS ou script de téléchargement)
6. Supprimer `refacto/`, `configtest/`, `WantedRH.jpg`
7. Ajouter validation schéma `rules.yaml`
8. Limiter FPS de traitement à 15 max

### 🟢 Long terme
9. Unifier `plate_bench.py` / `plate_bench_gui.py`
10. Tests unitaires sur la couche recognition
11. Convention commits enforced (commitlint ou hook pre-commit)
