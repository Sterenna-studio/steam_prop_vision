# RUNBOOK — STEAM Prop Vision

> Procédures d’exploitation de STYX. Ce document indique quoi exécuter, quoi vérifier et quoi collecter en cas de problème.
>
> Références : [README](README.md), [INSTALL](INSTALL.md), [PIPELINE](PIPELINE.md), [LOXONE](LOXONE.md) et [AUDIT](AUDIT.md).

## Démarrage express

| Je veux… | Action |
| --- | --- |
| Démarrer le pipeline | `python apps/rpi/main.py` |
| Utiliser le lanceur Linux existant | `./scripts/linux_run.sh` |
| Démarrer/relancer via systemd | `sudo systemctl restart steam-vision` |
| Lancer les tests | `pytest` puis `ruff check .` |
| Voir le flux et les métriques | Ouvrir `/view` sur STYX |
| Vérifier le démarrage complet | Ouvrir `:8890/monitor` et contrôler les badges verts |
| Consulter les logs récents | Ouvrir `:8890/logs-ui` |
| Gérer les templates actifs | Ouvrir `:8890/plates-ui` |
| Ajouter une plaque | Voir [Ajouter une plaque](#ajouter-une-plaque) |
| Déployer sur STYX | Voir [Déployer-sur-styx](#déployer-sur-styx) |

> La future façade `steam` remplacera progressivement ces points d’entrée. Tant qu’elle n’est pas fusionnée, les commandes ci-dessus sont les commandes de référence.

## Pré-requis

- STYX est démarré et joignable sur le réseau.
- La caméra est connectée et libre.
- L’environnement Python et les dépendances du projet sont installés.
- `config/features.yaml` et `config/rules.yaml` sont présents.
- Pour le QR, `libzbar0` et le backend ZBar sont installés sur STYX.

## Démarrer le système

### Démarrage normal

```bash
python apps/rpi/main.py
```

Succès attendu : la caméra s’ouvre, le pipeline atteint l’état `IDLE`, `/view` affiche le flux et les métriques, puis une plaque confirmée déclenche son action.

### Arrêt propre

Interrompre le processus avec `Ctrl+C`. Vérifier qu’aucun processus de pipeline ou lecteur média orphelin ne reste actif avant de relancer le système.

## Contrôle visuel terrain

1. Ouvrir `/view` sur STYX.
2. Vérifier l’orientation de l’image, les FPS et la présence du score ORB.
3. Présenter une plaque de référence.
4. Confirmer la reconnaissance, la confirmation temporelle, l’ajout à l’historique et l’exécution de l’action attendue.

Si l’image est tournée, ajuster `camera_rotation` dans `config/features.yaml`, puis redémarrer le pipeline.

### Contrôle de démarrage depuis le monitor

Ouvrir `http://<ip-styx>:8890/monitor`. Le démarrage est complet quand les
indicateurs affichent `CAM ON`, `PIPELINE ON`, `DETECTION ON` et `FRAMES OK`,
avec un nombre de templates et des FPS non nuls. Un indicateur rouge permet de
distinguer une API disponible d'une caméra ou d'une boucle figée.

### Historique disponible

`logs/steam_vision.log` et ses trois rotations conservent environ 8 Mio de logs
récents et sont consultables sur `:8890/logs-ui`. Le journal systemd complète
cet historique et permet de revenir aux boots précédents :

```bash
journalctl --list-boots
journalctl -u steam-vision -b -1 --no-pager
```

## Diagnostic rapide

### La caméra ne démarre pas

- Vérifier le câble, l’alimentation et que la caméra n’est pas utilisée par un autre processus.
- Relancer le pipeline après avoir arrêté les processus concurrents.
- En dernier recours, redémarrer STYX après avoir récupéré les logs utiles.

### Une plaque n’est pas reconnue

Vérifier dans cet ordre : orientation de l’image, éclairage, distance, angle, score ORB dans `/view`, présence des templates et paramètres de `config/features.yaml`. Ne modifier les seuils qu’après un test comparatif sur plusieurs plaques.

### Le QR de mission ne passe pas

- Vérifier le format `STEAM_FLUX:<mission_id>`.
- Vérifier la présence de `libzbar0`.
- Tester avec une mise au point et un éclairage stables.
- Considérer le fallback OpenCV comme secondaire.

### Loxone ne reçoit rien

1. Vérifier le réseau de STYX.
2. Vérifier `config/rules.yaml`.
3. Contrôler les logs d’ACK et de retry.
4. Tester `STEAM_PING`, `STEAM_RESET` ou `STEAM_TRIGGER:<card_id>` selon le scénario.

## Ajouter une plaque

1. Préparer les visuels et templates de la plaque.
2. Ouvrir `http://<ip-styx>:8890/plates-ui`, saisir un identifiant `plate_nom`
   et sélectionner les images. Le rechargement des descripteurs est automatique.
3. Configurer les actions dans l'éditeur de règles `:8890/`.
4. Vérifier que la plate apparaît `CHARGÉE`, puis tester la reconnaissance sous
   plusieurs distances, angles et éclairages.
5. N'activer la plaque qu'après une reconnaissance répétable et une action validée.

L'action « Archiver » retire la plate de la détection mais conserve ses fichiers
dans `.runtime/plate_trash/`. La section Archives de la même page permet de la
restaurer. Ces opérations modifient le clone local de STYX : vérifier
`git status` avant le prochain déploiement.

## Tests avant modification

```bash
ruff check .
pytest
```

Pour une modification de détection, compléter les tests automatisés par une validation matérielle avec caméra, plaques physiques et éclairage réel.

## Déployer sur STYX

1. Mettre à jour le code depuis une branche validée.
2. Installer ou actualiser les dépendances nécessaires.
3. Lancer les tests automatisés.
4. Démarrer le pipeline.
5. Vérifier `/view`, une plaque de référence et un QR de référence.
6. Vérifier l’action Loxone ou média attendue.

### Retour arrière

Revenir au dernier commit validé, restaurer les dépendances/configurations compatibles, redémarrer le pipeline et refaire le contrôle visuel terrain.

## Collecte avant escalade

Collecter avant de signaler un incident : date et heure, commit déployé, logs récents, capture de `/view` si le problème est visuel, plaque ou QR concerné, action attendue et action effectivement observée.

## Évolution du runbook

Après chaque incident ou session terrain, corriger immédiatement cette procédure : une commande qui a changé, un prérequis oublié ou un diagnostic inefficace doivent être mis à jour ici.
