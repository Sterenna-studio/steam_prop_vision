# Profils S.T.E.A.M Vision (contrat proposé)

Les profils sont préparés mais **ne remplacent pas** la configuration active
actuelle. Tant que `profiles/active.yaml` n'existe pas et que le runtime n'est
pas explicitement migré, `ProfileManager` retourne le profil rétrocompatible
`legacy`, qui pointe vers `config/rules.yaml`.

```text
profiles/
├── active.yaml                 # futur pointeur: active: mission_flux_1
├── mission_flux_1/profile.yaml
├── benchmark/profile.yaml
├── aruco_demo/profile.yaml
└── _archive/
```

Format :

```yaml
name: benchmark
backend: image_match
rules: config/rules.yaml
recognition:
  default_threshold: 0.20
  use_per_object_thresholds: false
objects:
  plate_cellule:
    threshold: 0.18
camera: {}
benchmark_reference: null
```

Les futures opérations admin (créer, dupliquer, renommer, archiver,
importer/exporter et activer) devront valider le profil avant de modifier le
pointeur actif. Une activation devra rester une action séparée et explicite.
