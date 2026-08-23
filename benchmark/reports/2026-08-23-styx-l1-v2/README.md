# Benchmark L1 v2 corrigé — STYX, 23 août 2026

Ce dossier publie le premier replay terrain des cinq stratégies L1 v2. Le
corpus privé a été capturé depuis `/stream` puis rejoué dans son orientation
stockée (`--camera-rotation 0`). Il corrige ainsi la double rotation du pilote
précédent.

Le service `steam-vision` était arrêté pendant toute la mesure puis a été
redémarré et vérifié `active`. Aucun réglage ni backend production n'a été
modifié.

## Configuration mesurée

- commit : `f4cfd3d8283d89969b8eaa285498397faff7d71a` ;
- STYX Raspberry Pi 5 / caméra IMX708 ;
- OpenCV 4.11.0 ;
- reconnaissance constante : variante A (ORB/ORB), MAGSAC, top-K 2 ;
- hold simulé : 1000 ms, 1 frame consécutive, grâce de 5 misses ;
- 320 frames : 300 positives, 20 négatives ;
- 15 présentations positives : cinq plaques × trois conditions ;
- ROI auto-calibrée sur 100 frontales, 78 contours utilisés :
  `x=0.0000, y=0.2553, w=0.9698, h=0.6568`.

## Résultats

| Stratégie | Recall frame | Présentations détectées | Triggers corrects | Precision observée | FPR négatifs | Latence p50/p95 |
|---|---:|---:|---:|---:|---:|---:|
| contour actuel | 18.33 % | 33.33 % | 33.33 % | 100.00 % | 0.00 % | 8.55 / 130.22 ms |
| full-frame fallback | **62.33 %** | **100.00 %** | **86.67 %** | 100.00 % | 0.00 % | 129.06 / 137.77 ms |
| ROI calibrée fallback | 47.67 % | 93.33 % | 66.67 % | 100.00 % | 0.00 % | 107.69 / 132.69 ms |
| qualité + fallback | 47.67 % | 93.33 % | 66.67 % | 100.00 % | 0.00 % | 107.75 / 132.45 ms |
| acquisition + tracking | 33.00 % | 93.33 % | 60.00 % | 100.00 % | 0.00 % | 103.39 / 154.38 ms |

Aucun trigger erroné ou négatif n'a été observé. Ce constat porte seulement
sur 20 frames négatives corrélées issues d'une unique scène : il ne permet pas
d'affirmer un FPR terrain nul.

Par condition, le contour actuel atteint 55 % de recall frontal et 0 % sur les
deux scénarios occultés. Le full-frame fallback atteint respectivement 73 %,
37 % avec main sur le bord et 77 % avec l'angle masqué. Il confirme que
l'occlusion bloque d'abord L1, mais reste sous le critère produit de 98 %.

## Lecture technique

- La ROI calibrée couvre 96,98 % de la largeur. Les plaques n'ont pas été
  présentées dans une zone fixe assez étroite : cette calibration ne réduit
  donc pas utilement la recherche.
- Avec le seuil qualité 0,55, 79 des 80 contours trouvés restent utilisés. La
  qualité rejette seulement un contour parasite négatif ; elle ne peut pas
  aider lorsque l'occlusion empêche entièrement la proposition.
- Le tracking expérimental dégrade le recall. Sa ROI se resserre ou dérive
  après acquisition et nécessite un mécanisme de revalidation/reacquisition
  avant tout nouveau test.
- Le full-frame fallback est le meilleur candidat pour la prochaine campagne,
  mais pas pour une activation production sur ce corpus limité.

Les fichiers JSON et CSV conservent le détail par frame, les sources de ROI,
les composantes qualité, les scores, les métriques L2/L3 et les événements de
trigger simulés. Aucune image ni template client n'est publié.

## Suite terrain recommandée

1. Capturer des hard negatives nombreux et indépendants.
2. Refaire les présentations avec plusieurs opérateurs, distances et lumières.
3. Capturer une série imposant une zone de présentation fixe pour évaluer une
   vraie ROI calibrée étroite.
4. Tester plusieurs seuils qualité sur les distributions enregistrées.
5. Revoir le tracking avec revalidation et abandon du lock, puis le rebenchmarker.
6. Répéter le full-frame fallback finaliste avant toute activation explicite.
