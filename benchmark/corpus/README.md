# Corpus officiel de benchmark vision

STATUS: corpus terrain STYX à capturer. Aucun résultat chiffré ne doit être
déduit des dossiers vides ou d'augmentations synthétiques.

## Structure

Chaque média est rangé sous l'identifiant attendu puis la condition :

```text
benchmark/corpus/
├── plate_cellule/
│   ├── frontal/
│   ├── proche/
│   ├── loin/
│   ├── angle_legere/
│   ├── angle_forte/
│   ├── rotation/
│   ├── occlusion/
│   ├── main_sur_bord/
│   ├── mouvement/
│   ├── motion_blur/
│   ├── faible_eclairage/
│   ├── reflet/
│   ├── fond_clair/
│   └── fond_sombre/
└── negatives/
    ├── aucune_plaque/
    ├── autre_plaque/
    ├── objets_ressemblants/
    └── quadrilateres_parasites/
```

Les images (`jpg`, `png`, `webp`, `bmp`) et vidéos (`mp4`, `avi`, `mov`,
`mkv`, `webm`) sont acceptées. Le chemin fournit automatiquement `expected`
et `condition`. Un sidecar YAML de même nom peut préciser ou remplacer ces
valeurs :

```yaml
expected: plate_cellule
condition: occlusion
severity: medium
notes: main sur bord gauche
sequence_id: cellule_occlusion_01
fps: 30
camera:
  lens_position: 4.25
```

Pour un négatif, utiliser `expected: null` ou le dossier `negatives/`.

## Protocole de capture

- Conserver cadrage, résolution, rotation et paramètres caméra réels.
- Capturer plusieurs répétitions et opérateurs, sans sélectionner seulement
  les essais réussis.
- Inclure frontal, proche, loin, inclinaisons légère/forte, rotation,
  occlusion partielle, doigt/main sur un bord, mouvement, flou, faible
  éclairage, reflet, fonds clair/sombre.
- Capturer des hard negatives : objets ressemblants, quadrilatères parasites,
  aucune plaque et autres plaques.
- Ne jamais copier automatiquement ce corpus dans `PLATEST`.

### Cas prioritaire : doigt ou main sur la plaque

Ce scénario doit être conservé même lorsque L1 ne trouve plus de quadrilatère :
un échec de contour est une mesure utile, pas une prise à écarter. Pour chaque
plaque, enregistrer au minimum le doigt sur les bords gauche, droit, haut et
bas, puis sur un angle. Faire varier approximativement l'occlusion entre
faible et moyenne et renseigner `severity` et `notes` :

```bash
python tools/capture_vision_corpus.py \
  --object plate_cellule --condition main_sur_bord \
  --severity medium --notes "doigt sur bord gauche" --duration 10 --fps 2
```

Le rapport doit distinguer le `L1_miss` de l'échec L2/L3. Un second passage
avec `--roi-mode full` ou `--roi-mode hybrid` permet ensuite de déterminer si
la faiblesse vient du contour L1 ou de la reconnaissance de la plaque occultée.

Sur STYX, le service de production peut rester actif : l'outil lit son flux
MJPEG sans ouvrir une seconde instance de Picamera2. Les captures vont par
défaut dans `.runtime/benchmark-corpus`, qui est ignoré par Git :

```bash
python tools/capture_vision_corpus.py \
  --object plate_cellule --condition frontal --duration 10 --fps 2

python tools/capture_vision_corpus.py \
  --negative --condition aucune_plaque --duration 10 --fps 2
```

Le compte à rebours par défaut est de trois secondes. Chaque image reçoit un
sidecar YAML avec son ground truth et son identifiant de séquence. Vérifier les
prises avant de retenir ou d'exporter le corpus ; ne pas sélectionner seulement
les détections réussies.

Le flux `/stream` est produit après application de `camera_rotation` par le
runtime. L'outil l'annote donc `camera.orientation: runtime-corrected`. Le
benchmark rejoue par défaut les fichiers tels qu'ils sont stockés, sans relire
la rotation de `features.yaml`. Utiliser `--camera-rotation` uniquement pour un
corpus réellement capturé dans l'orientation brute du capteur.
