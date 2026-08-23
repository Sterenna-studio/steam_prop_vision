# Benchmark L1 v2

**STATUS : outil offline disponible ; aucune stratégie L1 v2 activée en
production.**

Ce benchmark isole la sélection de la région d'intérêt (L1) de la chaîne de
reconnaissance. Il rejoue exactement le même corpus avec une reconnaissance
fixe, par défaut la variante A (ORB/ORB) et MAGSAC.

## Stratégies comparées

| Nom CLI | Comportement expérimental |
|---|---|
| `contour` | `FastDetector` actuel ; aucune ROI si le quadrilatère manque |
| `full_fallback` | contour, sinon frame complète |
| `calibrated_fallback` | contour, sinon ROI normalisée calibrée |
| `quality_fallback` | contour seulement si sa qualité est suffisante, sinon ROI calibrée |
| `acquisition_tracking` | politique qualité avant acquisition, puis flot optique sur une reconnaissance L2+L3 acceptée |

Ces stratégies vivent dans `steamcore/recognition/benchmark/`. Elles ne sont
ni importées ni sélectionnées par `apps/rpi/main.py`.

Le score qualité L1 expose séparément : régularité du quadrilatère, aire,
support des contours, contraste et stabilité temporelle. Ses poids et son
seuil sont des hypothèses de benchmark, pas des paramètres production.

## Lancer le benchmark

Le flux `/stream` de STYX est déjà tourné par le runtime. Un corpus capturé par
`tools/capture_vision_corpus.py` se rejoue donc avec la rotation par défaut de
zéro degré :

```bash
python tools/vision_l1_benchmark.py \
  --corpus .runtime/benchmark-corpus \
  --strategy all \
  --variant A \
  --homography magsac \
  --calibrated-roi auto \
  --report \
  --output .runtime/benchmark-l1-v2 \
  --hardware "STYX Raspberry Pi 5 / IMX708"
```

Une ROI connue peut remplacer l'auto-calibration :

```bash
python tools/vision_l1_benchmark.py \
  --strategy contour,calibrated_fallback,quality_fallback \
  --calibrated-roi 0.20,0.15,0.60,0.70 \
  --report
```

La calibration automatique utilise les détections de la condition `frontal`
sur les échantillons positifs. Le rapport conserve la ROI obtenue, le nombre
de frames examinées et le nombre de contours utilisés. Elle ne modifie aucun
fichier de configuration.

Options principales :

- `--quality-threshold` et `--tracking-threshold` ;
- `--hold-ms`, `--consec-frames`, `--miss-grace` pour reproduire une autre
  configuration temporelle ;
- `--top-k`, `--top2-margin`, `--object`, `--limit`, `--verbose` ;
- `--camera-rotation` seulement pour un corpus brut non orienté par le runtime.

## KPI décisionnels

Le JSON, le CSV et le Markdown séparent :

- recall/precision/FPR/FNR par frame ;
- taux de détection par présentation (au moins une frame correcte) ;
- taux de triggers corrects, erronés et négatifs ;
- temps de première détection et de trigger p50/p95 ;
- plus longue série de misses ;
- taux de contour et de fallback ;
- contribution de chaque source de ROI ;
- latence et résultats par objet/condition.

La simulation du hold suit le runtime actuel : la première reconnaissance
établit l'identité, une reconnaissance suivante démarre le hold, les misses
tolérés laissent le temps mural avancer, une identité différente réinitialise
immédiatement la séquence.

## Limites et décision production

Le tracking ne s'acquiert qu'après une reconnaissance L2+L3 acceptée ; le
ground truth du corpus n'est jamais utilisé pour le verrouiller. Cela évite de
donner artificiellement au benchmark une position inconnue du runtime.

Une hausse du recall par frame ne suffit pas : une stratégie candidate doit
améliorer les présentations et les triggers sans augmenter les faux positifs,
sur un corpus incluant des négatifs difficiles. Le seuil produit de 98 % et la
validation physique STYX restent obligatoires. Aucun résultat ne change
automatiquement le pipeline de production.
