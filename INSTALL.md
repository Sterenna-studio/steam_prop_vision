# Guide d'installation — S.T.E.A.M Vision

> Système de reconnaissance de cartes/plaques pour escape game  
> Raspberry Pi 5 (STYX) + IMX708 · Python 3.13

---

## Prérequis matériel

| Composant | Détail |
|---|---|
| **Raspberry Pi 5** | Machine cible (STYX) sous Debian Trixie |
| **Caméra IMX708** | Connectée via nappe CSI |
| **Box Loxone** | Réception UDP (IP locale, défaut `192.168.1.50`) |
| **PC de dev** | Windows 11 (Salomon) pour les outils et GitHub |

---

## 1. Cloner le projet

```bash
git clone https://github.com/Sterenna-studio/steam_prop_vision.git
cd steam_prop_vision
```

---

## 2. Installation — Raspberry Pi 5 (STYX)

Le Pi utilise un **venv avec `--system-site-packages`** pour accéder à `libcamera` (installé au niveau système).

```bash
# Créer le venv (depuis le dossier du projet)
python3 -m venv .venv --system-site-packages

# Activer le venv
source .venv/bin/activate

# Installer les dépendances Pi
pip install -r requirements_rpi.txt
```

> ⚠️ Utiliser `opencv-python-headless` sur le Pi (pas de display X11 nécessaire).  
> ⚠️ Vérifier que SIFT est disponible :
> ```bash
> python -c "import cv2; cv2.SIFT_create(); print('SIFT OK')"
> ```

---

## 3. Installation — PC de développement (Windows / Linux)

```bash
# Créer et activer le venv
python -m venv .venv
.venv\Scripts\activate        # Windows
# ou
source .venv/bin/activate     # Linux/macOS

# Installer les dépendances dev
pip install -r requirements.txt
```

> Sur Windows, double-cliquer sur `install_venv.bat` fait la même chose automatiquement.

---

## 4. Configuration

### 4.1 Paramètres pipeline — `config/features.yaml`

Tous les réglages sont centralisés ici, **sans toucher au code**.

```yaml
card_first: true          # Mode détection (recommandé)
require_person: true      # Exiger un joueur avant trigger
person_duration: 2.0      # Secondes de présence avant inspection
card_cooldown: 8.0        # Cooldown entre deux triggers
loxone_ip: 192.168.1.50   # IP de la box Loxone
yolo_model: yolov8n.pt    # Modèle YOLO utilisé
```

Éditer via GUI (recommandé sur le PC de dev) :
```bash
python tools/feature_gui.py
```

### 4.2 Règles de déclenchement — `config/rules.yaml`

Définit ce qui se passe quand une carte est reconnue :
- Message UDP envoyé à Loxone
- Son à jouer (`assets/audio/`)
- Vidéo à lancer (`assets/video/`)

### 4.3 Alias de lancement (Pi)

Ajouter dans `~/.bashrc` sur STYX pour l'alias `run_vision` :
```bash
echo "alias run_vision='bash /chemin/vers/steam_prop_vision/scripts/linux_run.sh'" >> ~/.bashrc
source ~/.bashrc
```

---

## 5. Préparer les cartes (PLATEST)

Chaque carte a son propre dossier dans `PLATEST/`. Ajouter **10 à 15 photos** par carte pour une bonne reconnaissance.

```
PLATEST/
├── plate_bougie/
│   ├── source.jpg          ← photo source originale
│   ├── sample_1234.jpg     ← photo réelle (prise avec le bench)
│   └── ...
├── plate_cellule/
├── plate_chaudron/
├── plate_dague/
└── plate_vampire/
```

### Générer les augmentations automatiques

```bash
# Toutes les cartes (15 variations par image)
python tools/generate_samples.py --all --count 15

# Une seule carte
python tools/generate_samples.py -i PLATEST/plate_bougie -n 20
```

---

## 6. Lancement

### Production (depuis STYX)

```bash
# Via alias
run_vision

# Équivalent complet
bash scripts/linux_run.sh --loxone 192.168.1.50

# Sans monitor WebSocket
bash scripts/linux_run.sh --loxone 192.168.1.50 --no-monitor
```

### Développement (PC Salomon)

```bash
# Lancer la GUI de setup
run_gui.bat              # ou : python gui_setup.py

# Lancer le builder de config
run_builder.bat
```

---

## 7. Outils de validation et calibration

### Bench de validation (recommandé avant mise en prod)

```bash
# Terminal (Pi ou PC)
python tools/plate_bench.py --pi

# Version GUI complète (scores + historique)
python tools/plate_bench_gui.py --pi
```

**Touches du bench :**

| Touche | Action |
|---|---|
| `1`–`5` | Changer la carte attendue |
| `ESPACE` | Capturer et tester |
| `A` | Sauvegarder le warp dans PLATEST |
| `R` | Recharger les templates |
| `Q` | Quitter + rapport final |

### Test interactif de la pipeline

```bash
python tools/pipeline_test.py [--pi]
```

Choisir au lancement entre :
- **RUN** — pipeline normale
- **DEV** — preview + overlay losange + scores ORB live
- **CALIBRATION** — ajuster `card_min_matches` et `card_score_threshold`

---

## 8. Monitor temps réel

La pipeline émet des events JSON via WebSocket :

```
ws://STYX_IP:8889
```

| Event | Contenu |
|---|---|
| `state` | `IDLE / INSPECTION / TRIGGERED` |
| `card_detected` | `card_id`, `label`, `score` |
| `count` | Nombre de joueurs détectés |
| `movement` | Direction, `dx`, `dy`, `speed` |
| `udp_sent` | Message envoyé à Loxone |

---

## 9. Workflow complet — mise en production

```
1. Fabriquer les plaques (Mecpow laser)
2. Photographier chaque plaque (10–15 photos, angles variés)
   → Copier dans PLATEST/plate_xxx/
3. Générer les augmentations :
   python tools/generate_samples.py --all --count 15
4. Valider avec le bench :
   python tools/plate_bench.py --pi
   → Touche A : sauvegarder les bons warps
   → Touche R : recharger les templates
5. Calibrer les seuils si besoin :
   python tools/pipeline_test.py --pi  (mode CALIBRATION)
6. Lancer en production :
   run_vision
```

---

## Dépannage rapide

| Problème | Solution |
|---|---|
| `SIFT_create` introuvable | Installer `opencv-contrib-python` (pas `opencv-python`) |
| Caméra non détectée | Vérifier `libcamera-hello` fonctionne hors venv |
| Aucun trigger Loxone | Vérifier IP dans `features.yaml` + pare-feu UDP 7777 |
| Score ORB trop bas | Ajouter plus de photos dans `PLATEST/`, re-générer augmentations |
| Pipeline freeze | Vérifier `inspect_timeout` dans `features.yaml` (défaut 15s) |
