# Rapport benchmark vision

- Date UTC : 2026-08-23T14:06:59.119139+00:00
- Commit Git : 536cd21fa4774434adf5b40cfabcc58cfaa61f79
- OpenCV : 4.11.0
- Matériel : STYX Raspberry Pi 5 / IMX708
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
| A | orb | magsac | 320 | 62.00 % | 100.00 % | 0 | 114 | 0.00 % | 38.00 % | 157.50 / 179.22 |
| B | sift | magsac | 320 | 61.00 % | 100.00 % | 0 | 117 | 0.00 % | 39.00 % | 613.67 / 656.53 |

## Temps et ressources

| Variante | Homographie | TTD p50/p95 (s) | Longest miss | CPU moyen | RAM pic (MB) | FPS moyen |
|---|---|---:|---:|---:|---:|---:|
| A | magsac | 0.00 / 1.15 | 19 | 256.72 % | 315.86 | 7.30 |
| B | magsac | 0.00 / 1.52 | 20 | 244.43 % | 3067.41 | 2.01 |

## Recall par objet

| Variante | Homographie | Objet | N | Recall |
|---|---|---|---:|---:|
| A | magsac | plate_bougie | 60 | 46.67 % |
| A | magsac | plate_cellule | 60 | 75.00 % |
| A | magsac | plate_chaudron | 60 | 75.00 % |
| A | magsac | plate_dague | 60 | 50.00 % |
| A | magsac | plate_vampire | 60 | 63.33 % |
| B | magsac | plate_bougie | 60 | 40.00 % |
| B | magsac | plate_cellule | 60 | 95.00 % |
| B | magsac | plate_chaudron | 60 | 53.33 % |
| B | magsac | plate_dague | 60 | 35.00 % |
| B | magsac | plate_vampire | 60 | 81.67 % |

## Métriques par condition

| Variante | Homographie | Condition | N | Recall | Precision | L1 hit | FPR |
|---|---|---|---:|---:|---:|---:|---:|
| A | magsac | aucune_plaque | 20 | N/A | N/A | 10.00 % | 0.00 % |
| A | magsac | frontal | 100 | 72.00 % | 100.00 % | 78.00 % | N/A |
| A | magsac | main_sur_bord | 100 | 37.00 % | 100.00 % | 10.00 % | N/A |
| A | magsac | occlusion_angle | 100 | 77.00 % | 100.00 % | 0.00 % | N/A |
| B | magsac | aucune_plaque | 20 | N/A | N/A | 10.00 % | 0.00 % |
| B | magsac | frontal | 100 | 76.00 % | 100.00 % | 78.00 % | N/A |
| B | magsac | main_sur_bord | 100 | 36.00 % | 100.00 % | 10.00 % | N/A |
| B | magsac | occlusion_angle | 100 | 71.00 % | 100.00 % | 0.00 % | N/A |

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

### B / magsac

```json
{
  "<negative>": {
    "<none>": 20
  },
  "plate_bougie": {
    "<none>": 36,
    "plate_bougie": 24
  },
  "plate_cellule": {
    "plate_cellule": 57,
    "<none>": 3
  },
  "plate_chaudron": {
    "plate_chaudron": 32,
    "<none>": 28
  },
  "plate_dague": {
    "<none>": 39,
    "plate_dague": 21
  },
  "plate_vampire": {
    "plate_vampire": 49,
    "<none>": 11
  }
}
```


## Recommandations de seuil

```json
{
  "plate_bougie": {
    "suggested_threshold": 0.1325,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_cellule": {
    "suggested_threshold": 0.105,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  },
  "plate_vampire": {
    "suggested_threshold": 0.1175,
    "method": "midpoint_between_observed_classes",
    "apply_automatically": false
  }
}
```

## Données non disponibles

`time_to_trigger` exige une simulation explicite du hold runtime et n'est
pas déduit artificiellement. CPU/RAM restent N/A sur les plateformes qui
ne permettent pas leur mesure sans dépendance supplémentaire.
