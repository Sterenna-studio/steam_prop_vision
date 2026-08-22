# Architecture de perception extensible

Le contrat cible est défini dans `steamcore/perception.py` :

```text
CAMERA
  ↓
PERCEPTION BACKEND
  ↓
PerceptionResult(id, confidence, backend, timestamp, corners?, bbox?, metadata)
  ↓
VALIDATION TEMPORELLE
  ↓
GAME LOGIC / RULES
```

`corners` et `bbox` sont optionnels afin de couvrir `image_match`, `person`,
`yolo_object`, `aruco`, `apriltag` et de futurs backends expérimentaux. La
migration de `apps/rpi/main.py` vers ce contrat n'est volontairement pas faite
dans ce chantier : le pipeline carte et le mode personne conservent leurs
types et leur comportement actuels.

## Backends préparés

- `image_match` : ORB/SIFT/AKAZE + homographie, benchmarkable A–E ;
- `aruco` / `apriltag` : `OpenCVFiducialBackend`, sortie `PerceptionResult` ;
- `person` / `yolo_object` : contrat documenté, adaptateur non branché ;
- `experimental` : réservé aux essais LightGlue/LoFTR, sans dépendance ajoutée.

## Calibration caméra

`steamcore/camera_calibration.py` reçoit un objet compatible Picamera2 par
injection, donc reste importable en CI. `CameraCalibrator` sait :

1. déclencher l'autofocus ;
2. attendre l'état focused/failed/timeout ;
3. échantillonner exposition et gain ;
4. exporter LensPosition, ExposureTime, AnalogueGain, ColourGains et autres
   metadata disponibles ;
5. verrouiller les valeurs observées sur demande ;
6. restaurer AE/AWB/autofocus automatiques.

Les valeurs de contrôles numériques suivent Picamera2/libcamera mais peuvent
être injectées via `CameraCalibrationControls`. Aucun contrôle n'est appliqué
par le runtime actuel. La calibration doit être testée physiquement avant tout
verrouillage en exploitation.

## Parcours admin préparé

Les services disponibles permettent le futur parcours : caméra → autofocus →
stabilisation → capture corpus → benchmark → seuils proposés → rapport →
profil. `steamcore/benchmark_setup.py` fournit la machine à états sérialisable
de ce parcours, sans lancer d'action matérielle implicitement. L'écran et les
endpoints d'orchestration ne sont pas ajoutés : lancer
un benchmark lourd depuis l'admin requiert d'abord une politique sûre de pause
caméra/service, d'espace disque et d'annulation. Aucun framework frontend n'est
justifié pour cette étape.

## Coût de YOLO

État du code :

- `ultralytics` est encore une dépendance obligatoire dans les deux fichiers de
  requirements ;
- `YOLODetector` importe Ultralytics en tête de `steamcore/detector.py` ;
- ce module n'est importé par `main.py` qu'à l'entrée de `run_person_mode` ;
- en mode carte, le modèle n'est donc ni chargé ni exécuté ; le coût runtime
  actif est nul hors packages installés et espace disque ;
- le modèle configuré est `yolov8n.pt`, mais sa présence/taille actuelle sur
  STYX doit être relevée, pas déduite d'une ancienne documentation.

| Mesure STYX | État |
|---|---|
| Taille packages Ultralytics/PyTorch | N/A — mesurer sur STYX |
| Taille du modèle | N/A — mesurer le fichier réellement déployé |
| RAM après import / après chargement | N/A — session matérielle requise |
| Temps de démarrage person | N/A — session matérielle requise |
| FPS / CPU person | N/A — corpus et STYX requis |
| Coût actif en mode card | aucun import/chargement de modèle dans le chemin actuel |

Séparer plus tard `vision-yolo` est techniquement possible, mais retirer
Ultralytics des requirements actuels casserait l'installation du mode
`person`. La séparation doit accompagner un installateur de profil et un boot
check explicite. Aucun package n'est déplacé dans ce chantier.

LightGlue/LoFTR ne sont pas ajoutés : PyTorch, poids et maintenance
alourdiraient la cible avant toute preuve sur le corpus classique.
