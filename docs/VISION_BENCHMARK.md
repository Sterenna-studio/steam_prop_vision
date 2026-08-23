# Benchmark vision S.T.E.A.M Vision

**STATUS: pilote terrain STYX capturé ; corpus de référence encore incomplet.**

Ce document décrit l'outil reproductible livré pour l'issue #9. Il ne contient
aucun chiffre de performance inventé. Les mesures du 23 août 2026 ci-dessous
proviennent d'un pilote réel sur STYX, mais ne constituent pas encore le corpus
de référence complet.

## Principe

Le benchmark est offline et ne remplace pas le pipeline de production. Chaque
combinaison reçoit les mêmes fichiers et, pour une vidéo, les mêmes frames dans
le même ordre.

| Variante | L2 | L3 |
|---|---|---|
| A | ORB | ORB (baseline production) |
| B | SIFT | ORB |
| C | AKAZE | ORB |
| D | ORB | intensité normalisée + gradients Sobel |
| E | AKAZE | intensité normalisée + gradients Sobel |

Les estimateurs `ransac` et `magsac` utilisent la même couche d'homographie.
Si `cv2.USAC_MAGSAC` est absent, le rapport conserve la demande `magsac`, note
`homography_fallback_used: true` et indique l'estimateur réellement utilisé
`ransac`. Il n'y a pas de fallback silencieux pour SIFT ou AKAZE : un backend
absent n'est pas remplacé par une autre méthode sous le même nom.

## Premier lancement

Depuis la racine du dépôt :

```bash
python tools/vision_benchmark.py \
  --corpus benchmark/corpus \
  --variant all \
  --homography all \
  --roi-mode l1 \
  --top-k 2 \
  --report
```

Exemples ciblés :

```bash
# Baseline A / RANSAC, 100 frames maximum
python tools/vision_benchmark.py --variant A --homography ransac --limit 100 --report

# Objet + négatifs associés, avec sauvegarde des échecs
python tools/vision_benchmark.py --object plate_cellule --save-failures --report

# Mesurer le fallback L1 sur full-frame sans modifier STYX
python tools/vision_benchmark.py --roi-mode hybrid --variant A,D --homography all --report

# Joindre le contexte matériel et un export de calibration YAML
python tools/vision_benchmark.py --hardware "STYX Pi 5 / IMX708" \
  --camera-parameters benchmark/configs/styx-camera.yaml --report
```

Options essentielles :

- `--variant A`, liste `A,B,D` ou `all` ;
- `--homography ransac`, `magsac`, liste ou `all` ;
- `--roi-mode l1|full|hybrid` (`l1` représente la barrière actuelle) ;
- `--object ID` conserve aussi les négatifs, indispensables à la precision ;
- `--top-k 1|2` et `--top2-margin` ;
- `--limit`, `--verbose`, `--save-failures` ;
- `--config` pour les seuils globaux/par objet ;
- `--output benchmark/reports`.

Le lancement sans corpus est valide pour tester l'installation. Il produit un
rapport vide indiquant explicitement `N/A — corpus terrain requis`.

## Corpus et ground truth

Le format officiel est décrit dans
[`benchmark/corpus/README.md`](../benchmark/corpus/README.md). Images et vidéos
sont supportées. Le chemin infère l'objet et la condition ; un sidecar YAML de
même nom fournit le ground truth détaillé.

Les scénarios obligatoires couvrent frontal, proche, loin, inclinaisons,
rotation, occlusion, main/doigt sur bord, mouvement, motion blur, faible
éclairage, reflet, fonds clair/sombre, objets ressemblants, quadrilatères
parasites, aucune plaque et autre plaque.

## Sorties

Avec `--report`, trois fichiers horodatés sont écrits dans
`benchmark/reports/` :

- JSON : contexte, agrégats et détail par frame ;
- CSV : détail tabulaire par frame ;
- Markdown : tableau A–E, recall par objet, métriques par condition, matrice de confusion et
  recommandations de seuil uniquement lorsque les classes observées sont
  séparables.

Les mesures incluent L1/L2/L3, latences, matches, inliers, ratio d'inliers,
erreur de reprojection médiane, aire/validité du quadrilatère, top-1/top-2,
marge, correction éventuelle de top-1, score, seuil utilisé, confusion,
time-to-first-detection et longest miss streak. FPS et CPU sont mesurés par le
runner ; RAM reste N/A lorsque la plateforme ne permet pas une mesure fiable
sans dépendance additionnelle. `time_to_trigger` reste N/A tant que le hold
runtime n'est pas explicitement simulé.

## Critère produit

> Un setup S.T.E.A.M Vision ne doit pas être considéré fiable si son taux de
> reconnaissance (recall) sur le corpus de référence est inférieur à 98 %.

Ce critère ne remplace pas les autres indicateurs. Le rapport affiche
séparément recall, precision, false positive rate et false negative rate. Une
variante avec un recall élevé mais des déclenchements sur hard negatives doit
être rejetée.

## État de référence

| Champ | Valeur |
|---|---|
| Date terrain | 2026-08-23 — pilote diagnostic |
| Commit mesuré | `536cd21` |
| Hardware | STYX — Raspberry Pi 5 / IMX708 |
| Paramètres caméra | N/A — calibration STYX requise |
| OpenCV | 4.11.0 |
| Nombre d'échantillons | 320 frames corrélées dans 16 séquences |
| Objets | cellule, vampire, bougie, chaudron, dague |
| Non mesurés | bois, ready-check, mouvements et conditions étendues |
| Choix production | pipeline actuel inchangé |

### Pilote occlusion du 23 août 2026

Le corpus local non versionné contient 300 frames positives et 20 frames
`aucune_plaque`. Pour chaque plaque disponible : 20 frames frontales, 20 avec
un doigt sur le bord gauche et 20 avec l'angle supérieur gauche masqué. Il ne
contient qu'un opérateur, une distance et une scène négative ; les frames d'une
même capture sont corrélées. Ces résultats ne valident donc ni le seuil de 98 %
ni une mise en production.

Résultats `hybrid` + MAGSAC :

| Variante | Recall | Precision | FPR négatifs | FNR | Latence p50/p95 propre |
|---|---:|---:|---:|---:|---:|
| A — ORB/ORB | 62.00 % | 100.00 % | 0.00 % sur 20 frames | 38.00 % | 124.33 / 140.32 ms |
| B — SIFT/ORB | 61.00 % | 100.00 % | 0.00 % sur 20 frames | 39.00 % | N/A — service actif pendant ce run |
| C — AKAZE/ORB | 46.33 % | 100.00 % | 0.00 % sur 20 frames | 53.67 % | 2371.83 / 3099.27 ms |
| D — ORB/apparence | 50.33 % | 100.00 % | 0.00 % sur 20 frames | 49.67 % | 113.17 / 121.96 ms |
| E — AKAZE/apparence | 25.00 % | 98.68 % | 0.00 % sur 20 frames | 75.00 % | 2370.91 / 3101.71 ms |

La precision à 100 % des variantes A à D signifie seulement qu'aucune
confusion finale n'a été observée dans ce petit pilote. Vingt frames négatives
ne suffisent pas à estimer un faux-positive rate terrain robuste. La variante E
a produit une confusion `plate_cellule → plate_bois`.

| Objet | A — ORB/ORB | B — SIFT/ORB |
|---|---:|---:|
| plate_bougie | 46.67 % | 40.00 % |
| plate_cellule | 75.00 % | 95.00 % |
| plate_chaudron | 75.00 % | 53.33 % |
| plate_dague | 50.00 % | 35.00 % |
| plate_vampire | 63.33 % | 81.67 % |

| Condition | L1 hit | A — ORB/ORB | B — SIFT/ORB |
|---|---:|---:|---:|
| frontal | 78.00 % | 72.00 % | 76.00 % |
| doigt sur bord gauche | 10.00 % | 37.00 % | 36.00 % |
| angle supérieur gauche masqué | 0.00 % | 77.00 % | 71.00 % |

Le doigt casse principalement le quadrilatère L1. Le plein cadre récupère des
frames de `plate_cellule`, mais n'améliore pas le corpus global : A passe de
62.00 % en hybride à 62.67 % en plein cadre, tandis que B passe de 61.00 % à
56.00 %. Le fallback doit donc être conditionné par une mesure de qualité L1
et validé objet par objet, pas activé globalement.

Sur la baseline A/hybride, RANSAC et MAGSAC donnent tous deux 62.00 % de recall.
Dans le run propre avec le service arrêté, MAGSAC mesure 124.33/140.32 ms
p50/p95 contre 157.85/419.22 ms pour RANSAC. Ce pilote justifie de poursuivre la
mesure, pas de changer l'estimateur de production.

Les rapports bruts expurgés d'images sont publiés dans
[`benchmark/reports/2026-08-23-styx-pilot/`](../benchmark/reports/2026-08-23-styx-pilot/).
Le corpus reste privé sur STYX sous `.runtime/benchmark-corpus` et n'est
volontairement ni copié dans `PLATEST`, ni versionné dans le dépôt public.

## Protocole terrain recommandé

1. Figer commit, versions et configuration caméra de STYX.
2. Capturer le corpus complet sans éliminer les prises difficiles.
3. Exécuter A–E × RANSAC/MAGSAC avec `--roi-mode l1`.
4. Rejouer le même corpus avec `hybrid` pour quantifier la barrière L1.
5. Examiner recall par objet et hard negatives avant toute recommandation de
   seuil.
6. Répéter les finalistes en conditions réelles pendant le hold.
7. Activer un backend en production seulement par changement explicite,
   réversible et validé sur STYX.
