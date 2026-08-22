# Templates runtime, corpus et augmentations

Trois rôles distincts doivent rester séparés :

1. **Runtime templates** — références validées chargées depuis `PLATEST` ;
2. **Benchmark samples** — observations terrain avec ground truth sous
   `benchmark/corpus` ;
3. **Offline stress-test augmentations** — transformations synthétiques pour
   provoquer des cas difficiles, hors runtime par défaut dans une future
   organisation.

`tools/generate_samples.py` ne produit pas un dataset de deep learning. Dans le
système de feature matching actuel, chaque `aug_*.jpg` placé dans `PLATEST`
devient une référence supplémentaire réellement comparée au runtime. Cela
augmente le temps, la mémoire de descripteurs et la surface de faux matches.

Le dépôt contient déjà des augmentations dans `PLATEST`. Elles ne sont ni
supprimées ni déplacées par ce chantier afin de ne pas modifier le comportement
de STYX. Les rapports doivent consigner le snapshot exact des templates.

## Flip horizontal

Le miroir horizontal est particulièrement dangereux : une plaque imprimée non
symétrique n'existe pas physiquement sous cette forme. Le flip peut introduire
des arrangements de features impossibles, rendre deux objets plus ambigus et
faire accepter une vue qui ne correspond pas au geste réel. Un flip doit vivre
dans un stress-test offline et ne devenir template runtime qu'après validation
explicite sur des négatifs.

## Migration future sans casse

La migration recommandée est additive :

```text
templates/runtime/<object_id>/
benchmark/corpus/<object_id>/<condition>/
benchmark/augmentations/<object_id>/
```

Elle nécessitera une option de chemin de templates, un manifeste de rôle et un
profil validé avant activation. Ne pas déplacer `PLATEST` sur STYX tant que
`main.py`, l'admin plates et les scripts d'exploitation ne lisent pas tous le
nouveau chemin.
