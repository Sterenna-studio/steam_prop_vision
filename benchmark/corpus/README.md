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
