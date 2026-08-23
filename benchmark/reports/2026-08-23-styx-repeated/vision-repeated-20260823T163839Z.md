# Campagne benchmark vision répétée

- Date UTC : 2026-08-23T16:38:39.266121+00:00
- Commit Git : ed3a6f161fab545b01b0a7d5c01437b68b160b4d
- OpenCV : 4.11.0
- Matériel : STYX Raspberry Pi 5 / IMX708
- Corpus : `/home/steam/steam_prop_vision/.runtime/benchmark-corpus`
- ROI : `hybrid`
- Répétitions : `5` ; warm-up : `10` frames/configuration ; seed : `9`
- Orientation ajoutée : `0°`

> Chaque passe reçoit le même corpus. L'ordre des configurations est
> mélangé de façon déterministe afin de limiter les biais d'ordre.

## Agrégats inter-runs

| Variante | Homographie | Runs | Recall moyen [min–max] | Precision moyenne | FPR moyen | Latence p50 moyenne [min–max] ms | Latence p95 moyenne [min–max] ms |
|---|---|---:|---:|---:|---:|---:|---:|
| A | magsac | 5 | 62.33 % [62.33 %–62.33 %] | 100.00 % | 0.00 % | 123.10 [122.90–123.33] | 138.75 [138.55–139.10] |
| A | ransac | 5 | 62.33 % [62.33 %–62.33 %] | 100.00 % | 0.00 % | 155.90 [155.73–156.27] | 413.75 [412.64–417.10] |
| B | magsac | 5 | 60.33 % [60.33 %–60.33 %] | 100.00 % | 0.00 % | 477.65 [476.99–478.02] | 508.09 [507.61–509.02] |
| B | ransac | 5 | 60.00 % [60.00 %–60.00 %] | 100.00 % | 0.00 % | 1279.20 [1275.80–1281.43] | 1723.80 [1721.86–1726.79] |

## Ordre d'exécution

- Passe 1 : `B/magsac → B/ransac → A/magsac → A/ransac`
- Passe 2 : `A/ransac → A/magsac → B/ransac → B/magsac`
- Passe 3 : `A/ransac → B/ransac → A/magsac → B/magsac`
- Passe 4 : `B/magsac → A/ransac → A/magsac → B/ransac`
- Passe 5 : `A/magsac → B/magsac → B/ransac → A/ransac`

## Résultats par passe

| Passe | Ordre | Variante | Homographie | Recall | Precision | FPR | Latence p50/p95 ms | Temps mural s |
|---:|---:|---|---|---:|---:|---:|---:|---:|
| 1 | 1 | B | magsac | 60.33 % | 100.00 % | 0.00 % | 478.02 / 509.02 | 174.81 |
| 1 | 2 | B | ransac | 60.00 % | 100.00 % | 0.00 % | 1277.55 / 1721.86 | 442.46 |
| 1 | 3 | A | magsac | 62.33 % | 100.00 % | 0.00 % | 122.98 / 138.71 | 44.94 |
| 1 | 4 | A | ransac | 62.33 % | 100.00 % | 0.00 % | 155.81 / 412.64 | 65.28 |
| 2 | 1 | A | ransac | 62.33 % | 100.00 % | 0.00 % | 155.73 / 417.10 | 65.33 |
| 2 | 2 | A | magsac | 62.33 % | 100.00 % | 0.00 % | 123.15 / 138.55 | 45.01 |
| 2 | 3 | B | ransac | 60.00 % | 100.00 % | 0.00 % | 1281.35 / 1724.63 | 443.47 |
| 2 | 4 | B | magsac | 60.33 % | 100.00 % | 0.00 % | 477.76 / 507.77 | 174.92 |
| 3 | 1 | A | ransac | 62.33 % | 100.00 % | 0.00 % | 155.88 / 412.91 | 65.34 |
| 3 | 2 | B | ransac | 60.00 % | 100.00 % | 0.00 % | 1279.90 / 1726.79 | 443.36 |
| 3 | 3 | A | magsac | 62.33 % | 100.00 % | 0.00 % | 122.90 / 138.67 | 44.97 |
| 3 | 4 | B | magsac | 60.33 % | 100.00 % | 0.00 % | 477.75 / 507.61 | 174.85 |
| 4 | 1 | B | magsac | 60.33 % | 100.00 % | 0.00 % | 476.99 / 507.62 | 174.63 |
| 4 | 2 | A | ransac | 62.33 % | 100.00 % | 0.00 % | 156.27 / 412.89 | 65.39 |
| 4 | 3 | A | magsac | 62.33 % | 100.00 % | 0.00 % | 123.14 / 138.71 | 44.98 |
| 4 | 4 | B | ransac | 60.00 % | 100.00 % | 0.00 % | 1275.80 / 1722.11 | 442.20 |
| 5 | 1 | A | magsac | 62.33 % | 100.00 % | 0.00 % | 123.33 / 139.10 | 45.02 |
| 5 | 2 | B | magsac | 60.33 % | 100.00 % | 0.00 % | 477.72 / 508.43 | 175.09 |
| 5 | 3 | B | ransac | 60.00 % | 100.00 % | 0.00 % | 1281.43 / 1723.60 | 443.50 |
| 5 | 4 | A | ransac | 62.33 % | 100.00 % | 0.00 % | 155.80 / 413.23 | 65.33 |

Les distributions inter-runs ne remplacent pas une campagne terrain
diversifiée. Aucun résultat n'est appliqué automatiquement en production.
