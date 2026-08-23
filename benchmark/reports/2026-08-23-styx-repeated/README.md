# Campagne répétée A/B × RANSAC/MAGSAC — STYX

Campagne terrain offline réalisée le 23 août 2026 sur STYX, au commit
`ed3a6f161fab545b01b0a7d5c01437b68b160b4d`.

Le service production a été arrêté pendant la mesure, puis redémarré et
vérifié sain : caméra et pipeline actifs, sept templates chargés. Aucun
paramètre de production n'a été modifié.

## Protocole

- Raspberry Pi 5 / IMX708 / OpenCV 4.11.0 ;
- corpus privé corrigé : 320 frames, orientation ajoutée 0° ;
- ROI `hybrid` : contour si présent, full-frame sinon ;
- variantes A (ORB/ORB) et B (SIFT/ORB) ;
- RANSAC et USAC_MAGSAC ;
- 5 passes complètes, 10 frames de warm-up par configuration ;
- ordre mélangé de façon reproductible avec la seed 9 ;
- 20 replays complets, soit 6 400 frames mesurées plus 40 warm-ups ;
- température observée sous charge : 64,2–71,4 °C ; `get_throttled=0x0`.

## Résultats inter-runs

| Variante | Estimateur | Recall, 5/5 runs | Precision observée | FPR négatifs | Latence p50 moyenne | Latence p95 moyenne | Temps mural moyen/run |
|---|---|---:|---:|---:|---:|---:|---:|
| A ORB/ORB | MAGSAC | **62,33 %** | 100 % | 0 % | **123,10 ms** | **138,75 ms** | **44,98 s** |
| A ORB/ORB | RANSAC | **62,33 %** | 100 % | 0 % | 155,90 ms | 413,75 ms | 65,33 s |
| B SIFT/ORB | MAGSAC | **60,33 %** | 100 % | 0 % | **477,65 ms** | **508,09 ms** | **174,86 s** |
| B SIFT/ORB | RANSAC | 60,00 % | 100 % | 0 % | 1 279,20 ms | 1 723,80 ms | 443,00 s |

Le recall et les taux d'erreur sont identiques sur les cinq répétitions de
chaque configuration (`std=0`). Les latences présentent elles aussi une très
faible dispersion malgré les ordres différents.

Par rapport à RANSAC, MAGSAC réduit sur cette campagne :

- A : p50 d'environ 21,0 %, p95 d'environ 66,5 %, temps mural d'environ 31,1 % ;
- B : p50 d'environ 62,7 %, p95 d'environ 70,5 %, temps mural d'environ 60,5 %.

B/MAGSAC reconnaît une frame de plus que B/RANSAC, mais reste légèrement sous
A en recall global et environ 3,9 fois plus lent en p50. Ces résultats
renforcent MAGSAC comme candidat de benchmark et A comme socle actuel. Ils ne
suffisent pas à modifier le défaut production : le corpus ne contient toujours
qu'une séquence négative et aucune configuration n'approche le critère de 98 %.

## Top-K sur le run L1 v2 associé

Pour `full_fallback` A/MAGSAC, un top-2 L2 existe sur seulement 8 des 320
frames. Toutes les marges top1–top2 sont supérieures à 0,10 et L3 ne corrige
aucun top-1. Le top-2 conditionnel n'apporte donc aucun gain observé sur ce
petit corpus ; il reste instrumenté pour un futur corpus plus ambigu.

Les fichiers JSON/CSV/Markdown conservent les ordres exacts et chaque run. Ils
ne contiennent aucune image ni template client.
