# Benchmark vision S.T.E.A.M Vision

**STATUS: corpus terrain STYX à capturer.**

Ce document décrit l'outil reproductible livré pour l'issue #9. Il ne contient
aucun chiffre de performance inventé : recall, precision, latence, CPU, RAM et
FPS sont **N/A — corpus terrain requis** tant qu'un corpus de référence n'a pas
été capturé et rejoué sur STYX.

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
- Markdown : tableau A–E, recall par objet, matrice de confusion et
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
| Date terrain | N/A — corpus terrain requis |
| Commit mesuré | N/A — généré au lancement |
| Hardware | N/A — à renseigner sur STYX |
| Paramètres caméra | N/A — calibration STYX requise |
| OpenCV | N/A — collecté automatiquement |
| Nombre d'échantillons | 0 |
| Recall / precision / FPR / FNR | N/A — corpus terrain requis |
| Choix production | pipeline actuel inchangé |

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
