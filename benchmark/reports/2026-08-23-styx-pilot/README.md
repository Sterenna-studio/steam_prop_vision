# Pilote terrain STYX — 23 août 2026

> **SUPERSEDED POUR LA DÉCISION :** ce pilote a rejoué à 90° des images déjà
> orientées par le flux runtime. Les artefacts restent publiés pour audit, mais
> leurs chiffres ne doivent pas guider un choix de production. Le replay corrigé
> utilise `--camera-rotation 0` et sera publié séparément.

Ces rapports ont été produits sur un Raspberry Pi 5 STYX équipé d'une caméra
IMX708 et d'OpenCV 4.11.0, au commit benchmark `536cd21`. Ils sont publiés pour
rendre les comparaisons auditables ; ils ne constituent pas encore le corpus
de référence qualifiant un setup S.T.E.A.M Vision.

Le corpus image reste privé sur STYX. Aucun visuel client, template PLATEST,
secret ou adresse réseau n'est inclus dans ce dossier.

## Périmètre

- 320 frames terrain réparties dans 16 séquences corrélées ;
- 300 positives : bougie, cellule, chaudron, dague et vampire ;
- 20 négatives issues d'une seule séquence `aucune_plaque` ;
- conditions positives : frontal, doigt sur le bord gauche et angle supérieur
  gauche masqué ;
- un opérateur et un seul setup caméra ;
- `plate_bois` non mesurée, car indisponible physiquement.

## Jeux de rapports

Chaque dossier contient le Markdown synthétique, le CSV par frame et le JSON
complet générés par `tools/vision_benchmark.py`.

| Dossier | Variantes | ROI | Homographie | État production | Usage |
|---|---|---|---|---|---|
| [`baseline-clean/`](baseline-clean/) | A | hybrid | RANSAC + MAGSAC | arrêtée | comparaison propre des estimateurs et latences baseline |
| [`ab-hybrid/`](ab-hybrid/) | A, B | hybrid | MAGSAC | active | comparaison fonctionnelle ORB/SIFT ; latences non décisionnelles |
| [`ab-full/`](ab-full/) | A, B | full | MAGSAC | état mixte pendant le run | contrôle du fallback plein cadre ; latences non décisionnelles |
| [`cde-hybrid/`](cde-hybrid/) | C, D, E | hybrid | MAGSAC | arrêtée | AKAZE et L3 apparence globale |

Le nombre de lignes brutes vaut `320 × nombre de configurations` : 640 pour
les rapports à deux configurations et 960 pour C/D/E.

## Résultats comparables A–E

Mode `hybrid`, estimateur MAGSAC :

| Variante | L2 | L3 | Recall | Precision | FNR |
|---|---|---|---:|---:|---:|
| A | ORB | ORB | 62.00 % | 100.00 % | 38.00 % |
| B | SIFT | ORB | 61.00 % | 100.00 % | 39.00 % |
| C | AKAZE | ORB | 46.33 % | 100.00 % | 53.67 % |
| D | ORB | apparence globale | 50.33 % | 100.00 % | 49.67 % |
| E | AKAZE | apparence globale | 25.00 % | 98.68 % | 75.00 % |

La precision observée ne doit pas être extrapolée : les 20 frames négatives
proviennent d'une seule scène. La variante E a produit une confusion positive
`plate_cellule → plate_bois`, qui diminue sa precision sans augmenter le FPR
calculé uniquement sur les négatifs.

## Conclusion mesurée

L1 trouve 78 % des frames frontales, 10 % des prises avec doigt sur le bord et
0 % des angles masqués. L'occlusion casse donc principalement la recherche du
quadrilatère. Le plein cadre ne constitue toutefois pas un fallback global
suffisant : A passe de 62.00 % en hybride à 62.67 % en plein cadre, et B de
61.00 % à 56.00 %.

Sur A/hybride, RANSAC et MAGSAC donnent chacun 62.00 % de recall. Dans le run
propre, MAGSAC mesure 124.33/140.32 ms p50/p95, contre 157.85/419.22 ms pour
RANSAC. Cette observation ne modifie pas la configuration production.

Le critère produit de 98 % n'est atteint par aucune variante. La prochaine
étape est d'élargir les négatifs, opérateurs, distances et conditions, puis de
mesurer un fallback basé sur une qualité géométrique L1 explicite.

## Reproduction

Le corpus privé peut être rejoué sur STYX avec :

```bash
sudo systemctl stop steam-vision

python tools/vision_benchmark.py \
  --corpus .runtime/benchmark-corpus \
  --variant all \
  --homography all \
  --roi-mode hybrid \
  --top-k 2 \
  --report \
  --output .runtime/benchmark-reports-replay \
  --hardware "STYX Raspberry Pi 5 / IMX708"

sudo systemctl start steam-vision
sudo systemctl is-active steam-vision
```

Les chiffres complets, la configuration, la matrice de confusion et les
métriques par condition se trouvent dans les fichiers JSON et Markdown liés
ci-dessus.
