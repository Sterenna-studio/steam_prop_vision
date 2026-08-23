# Rapport benchmark vision

- Date UTC : 2026-08-23T14:37:38.822392+00:00
- Commit Git : 536cd21fa4774434adf5b40cfabcc58cfaa61f79
- OpenCV : 4.11.0
- Matériel : STYX Raspberry Pi 5 / IMX708 / production service stopped
- Paramètres caméra : N/A — non renseignés
- Corpus : `/home/steam/steam_prop_vision/.runtime/benchmark-corpus`
- Templates runtime : `/home/steam/steam_prop_vision/PLATEST`
- ROI : `hybrid`

> Critère produit : un setup S.T.E.A.M Vision n'est pas considéré fiable
> si son recall sur le corpus de référence est inférieur à 98 %. La
> precision et les taux de faux positifs/négatifs restent évalués séparément.

## Comparaison A–E

| Variante | L2 | Homographie demandée | N | Recall | Precision | FP | FN | FPR | FNR | Latence p50/p95 (ms) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C | akaze | magsac | 320 | 46.33 % | 100.00 % | 0 | 161 | 0.00 % | 53.67 % | 2371.83 / 3099.27 |
| D | orb | magsac | 320 | 50.33 % | 100.00 % | 0 | 149 | 0.00 % | 49.67 % | 113.17 / 121.96 |
| E | akaze | magsac | 320 | 25.00 % | 98.68 % | 1 | 225 | 0.00 % | 75.00 % | 2370.91 / 3101.71 |

## Temps et ressources

| Variante | Homographie | TTD p50/p95 (s) | Longest miss | CPU moyen | RAM pic (MB) | FPS moyen |
|---|---|---:|---:|---:|---:|---:|
| C | magsac | 0.00 / 4.40 | 20 | 369.68 % | 1877.09 | 1.15 |
| D | magsac | 0.50 / 1.15 | 19 | 308.98 % | 1877.09 | 9.68 |
| E | magsac | 0.00 / 4.50 | 20 | 367.56 % | 1963.66 | 1.13 |

## Recall par objet

| Variante | Homographie | Objet | N | Recall |
|---|---|---|---:|---:|
| C | magsac | plate_bougie | 60 | 28.33 % |
| C | magsac | plate_cellule | 60 | 56.67 % |
| C | magsac | plate_chaudron | 60 | 61.67 % |
| C | magsac | plate_dague | 60 | 45.00 % |
| C | magsac | plate_vampire | 60 | 40.00 % |
| D | magsac | plate_bougie | 60 | 36.67 % |
| D | magsac | plate_cellule | 60 | 65.00 % |
| D | magsac | plate_chaudron | 60 | 51.67 % |
| D | magsac | plate_dague | 60 | 46.67 % |
| D | magsac | plate_vampire | 60 | 51.67 % |
| E | magsac | plate_bougie | 60 | 8.33 % |
| E | magsac | plate_cellule | 60 | 26.67 % |
| E | magsac | plate_chaudron | 60 | 36.67 % |
| E | magsac | plate_dague | 60 | 43.33 % |
| E | magsac | plate_vampire | 60 | 10.00 % |

## Métriques par condition

| Variante | Homographie | Condition | N | Recall | Precision | L1 hit | FPR |
|---|---|---|---:|---:|---:|---:|---:|
| C | magsac | aucune_plaque | 20 | N/A | N/A | 10.00 % | 0.00 % |
| C | magsac | frontal | 100 | 30.00 % | 100.00 % | 78.00 % | N/A |
| C | magsac | main_sur_bord | 100 | 22.00 % | 100.00 % | 10.00 % | N/A |
| C | magsac | occlusion_angle | 100 | 87.00 % | 100.00 % | 0.00 % | N/A |
| D | magsac | aucune_plaque | 20 | N/A | N/A | 10.00 % | 0.00 % |
| D | magsac | frontal | 100 | 69.00 % | 100.00 % | 78.00 % | N/A |
| D | magsac | main_sur_bord | 100 | 36.00 % | 100.00 % | 10.00 % | N/A |
| D | magsac | occlusion_angle | 100 | 46.00 % | 100.00 % | 0.00 % | N/A |
| E | magsac | aucune_plaque | 20 | N/A | N/A | 10.00 % | 0.00 % |
| E | magsac | frontal | 100 | 30.00 % | 96.77 % | 78.00 % | N/A |
| E | magsac | main_sur_bord | 100 | 24.00 % | 100.00 % | 10.00 % | N/A |
| E | magsac | occlusion_angle | 100 | 21.00 % | 100.00 % | 0.00 % | N/A |

## Matrice de confusion

### C / magsac

```json
{
  "<negative>": {
    "<none>": 20
  },
  "plate_bougie": {
    "plate_bougie": 17,
    "<none>": 43
  },
  "plate_cellule": {
    "<none>": 26,
    "plate_cellule": 34
  },
  "plate_chaudron": {
    "plate_chaudron": 37,
    "<none>": 23
  },
  "plate_dague": {
    "plate_dague": 27,
    "<none>": 33
  },
  "plate_vampire": {
    "<none>": 36,
    "plate_vampire": 24
  }
}
```

### D / magsac

```json
{
  "<negative>": {
    "<none>": 20
  },
  "plate_bougie": {
    "<none>": 38,
    "plate_bougie": 22
  },
  "plate_cellule": {
    "<none>": 21,
    "plate_cellule": 39
  },
  "plate_chaudron": {
    "plate_chaudron": 31,
    "<none>": 29
  },
  "plate_dague": {
    "plate_dague": 28,
    "<none>": 32
  },
  "plate_vampire": {
    "plate_vampire": 31,
    "<none>": 29
  }
}
```

### E / magsac

```json
{
  "<negative>": {
    "<none>": 20
  },
  "plate_bougie": {
    "plate_bougie": 5,
    "<none>": 55
  },
  "plate_cellule": {
    "<none>": 43,
    "plate_bois": 1,
    "plate_cellule": 16
  },
  "plate_chaudron": {
    "plate_chaudron": 22,
    "<none>": 38
  },
  "plate_dague": {
    "plate_dague": 26,
    "<none>": 34
  },
  "plate_vampire": {
    "<none>": 54,
    "plate_vampire": 6
  }
}
```


## Recommandations de seuil

```json
{
  "plate_bougie": {
    "suggested_threshold": 0.2718,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_chaudron": {
    "suggested_threshold": 0.1994,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_dague": {
    "suggested_threshold": 0.115,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_vampire": {
    "suggested_threshold": 0.181,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  }
}
```

## Données non disponibles

`time_to_trigger` exige une simulation explicite du hold runtime et n'est
pas déduit artificiellement. CPU/RAM restent N/A sur les plateformes qui
ne permettent pas leur mesure sans dépendance supplémentaire.
