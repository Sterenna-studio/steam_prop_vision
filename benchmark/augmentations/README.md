# Augmentations de stress-test offline

Ce dossier est séparé de `PLATEST` : les fichiers générés ici ne sont jamais
chargés par le runtime. Pour une image source unique :

```bash
python tools/generate_samples.py \
  --input PLATEST/plate_cellule/source.jpg \
  --out benchmark/augmentations/plate_cellule \
  --count 30 --seed 42
```

Ne recopier une augmentation dans `PLATEST` qu'après validation explicite sur
le corpus terrain et les hard negatives. Les flips horizontaux doivent rester
offline sauf justification physique démontrée.
