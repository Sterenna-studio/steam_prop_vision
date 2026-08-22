# Marqueurs fiduciaires ArUco et AprilTag

S.T.E.A.M Vision prépare deux backends fondés sur le module `cv2.aruco` : ArUco
et les familles AprilTag exposées par OpenCV. Ils produisent le même
`PerceptionResult` et peuvent associer un ID numérique à un identifiant de
règle.

## Disponibilité réelle

Le module `aruco` dépend d'une build OpenCV qui l'inclut (souvent OpenCV
contrib). Le logiciel échoue explicitement avec `FiducialUnavailableError` s'il
est absent. Les familles AprilTag disponibles dépendent de la version OpenCV ;
vérifier par exemple `DICT_APRILTAG_36h11` sur STYX avant de créer un profil.
Aucune bibliothèque AprilTag tierce n'est ajoutée.

## Génération

```bash
# ArUco PNG + SVG, marqueur physique 80 mm et marge blanche 8 mm
python tools/fiducial_marker.py --family DICT_4X4_50 --id 7 \
  --png marker-7.png --svg marker-7.svg --size-mm 80 --margin-mm 8

# AprilTag via le dictionnaire OpenCV
python tools/fiducial_marker.py --backend apriltag \
  --family DICT_APRILTAG_36h11 --id 12 --svg tag-12.svg
```

Le SVG est vectoriel et dimensionné en millimètres. Le PNG sert au preview ou
à un test synthétique ; conserver l'échelle physique à l'impression.

## Choix et fabrication

- Choisir un dictionnaire assez grand pour les IDs du projet, sans gonfler
  inutilement la densité de cellules.
- Garder une marge blanche (quiet zone) intacte autour du bord noir.
- Imprimer/graver avec contraste fort, sans mise à l'échelle automatique.
- Éviter support brillant, déformation, faible résolution et découpe de marge.
- Mesurer la taille noire finale, noter la distance caméra et tester les angles,
  mouvements, reflets et occlusions du corpus officiel.
- Pour la gravure, vérifier que les cellules restent pleines et que le matériau
  ne réduit pas le contraste infrarouge/visible de la caméra.

## Association ID → règle

```python
from steamcore.recognition.fiducials import create_aruco_backend

backend = create_aruco_backend("DICT_4X4_50", {7: "porte_labo"})
results = backend.detect(frame)
```

L'association à `rules.yaml` et l'activation depuis un profil restent à faire.
Le backend n'est pas injecté dans `main.py` automatiquement.
