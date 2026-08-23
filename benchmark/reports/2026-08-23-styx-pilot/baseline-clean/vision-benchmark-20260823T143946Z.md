# Rapport benchmark vision

- Date UTC : 2026-08-23T14:39:46.355169+00:00
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
| A | orb | magsac | 320 | 62.00 % | 100.00 % | 0 | 114 | 0.00 % | 38.00 % | 124.33 / 140.32 |
| A | orb | ransac | 320 | 62.00 % | 100.00 % | 0 | 114 | 0.00 % | 38.00 % | 157.85 / 419.22 |

## Temps et ressources

| Variante | Homographie | TTD p50/p95 (s) | Longest miss | CPU moyen | RAM pic (MB) | FPS moyen |
|---|---|---:|---:|---:|---:|---:|
| A | magsac | 0.00 / 1.15 | 19 | 311.48 % | 323.34 | 9.01 |
| A | ransac | 0.00 / 1.15 | 19 | 260.25 % | 312.72 | 6.85 |

## Recall par objet

| Variante | Homographie | Objet | N | Recall |
|---|---|---|---:|---:|
| A | magsac | plate_bougie | 60 | 46.67 % |
| A | magsac | plate_cellule | 60 | 75.00 % |
| A | magsac | plate_chaudron | 60 | 75.00 % |
| A | magsac | plate_dague | 60 | 50.00 % |
| A | magsac | plate_vampire | 60 | 63.33 % |
| A | ransac | plate_bougie | 60 | 43.33 % |
| A | ransac | plate_cellule | 60 | 68.33 % |
| A | ransac | plate_chaudron | 60 | 75.00 % |
| A | ransac | plate_dague | 60 | 55.00 % |
| A | ransac | plate_vampire | 60 | 68.33 % |

## Métriques par condition

| Variante | Homographie | Condition | N | Recall | Precision | L1 hit | FPR |
|---|---|---|---:|---:|---:|---:|---:|
| A | magsac | aucune_plaque | 20 | N/A | N/A | 10.00 % | 0.00 % |
| A | magsac | frontal | 100 | 72.00 % | 100.00 % | 78.00 % | N/A |
| A | magsac | main_sur_bord | 100 | 37.00 % | 100.00 % | 10.00 % | N/A |
| A | magsac | occlusion_angle | 100 | 77.00 % | 100.00 % | 0.00 % | N/A |
| A | ransac | aucune_plaque | 20 | N/A | N/A | 10.00 % | 0.00 % |
| A | ransac | frontal | 100 | 76.00 % | 100.00 % | 78.00 % | N/A |
| A | ransac | main_sur_bord | 100 | 34.00 % | 100.00 % | 10.00 % | N/A |
| A | ransac | occlusion_angle | 100 | 76.00 % | 100.00 % | 0.00 % | N/A |

## Matrice de confusion

### A / magsac

```json
{
  "<negative>": {
    "<none>": 20
  },
  "plate_bougie": {
    "<none>": 32,
    "plate_bougie": 28
  },
  "plate_cellule": {
    "<none>": 15,
    "plate_cellule": 45
  },
  "plate_chaudron": {
    "plate_chaudron": 45,
    "<none>": 15
  },
  "plate_dague": {
    "plate_dague": 30,
    "<none>": 30
  },
  "plate_vampire": {
    "plate_vampire": 38,
    "<none>": 22
  }
}
```

### A / ransac

```json
{
  "<negative>": {
    "<none>": 20
  },
  "plate_bougie": {
    "<none>": 34,
    "plate_bougie": 26
  },
  "plate_cellule": {
    "<none>": 19,
    "plate_cellule": 41
  },
  "plate_chaudron": {
    "plate_chaudron": 45,
    "<none>": 15
  },
  "plate_dague": {
    "plate_dague": 33,
    "<none>": 27
  },
  "plate_vampire": {
    "plate_vampire": 41,
    "<none>": 19
  }
}
```


## Recommandations de seuil

```json
{
  "plate_bougie": {
    "suggested_threshold": 0.1375,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_cellule": {
    "suggested_threshold": 0.1144,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_chaudron": {
    "suggested_threshold": 0.13,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_dague": {
    "suggested_threshold": 0.1613,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_vampire": {
    "suggested_threshold": 0.1087,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  }
}
```

## Données non disponibles

`time_to_trigger` exige une simulation explicite du hold runtime et n'est
pas déduit artificiellement. CPU/RAM restent N/A sur les plateformes qui
ne permettent pas leur mesure sans dépendance supplémentaire.
