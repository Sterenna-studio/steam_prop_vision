# Legacy — ancien système "Sim Env" (non maintenu)

> ⚠️ **Ne pas utiliser en production.** Ce dossier existe uniquement pour conserver
> l'historique et le code d'une ancienne approche, remplacée par la pipeline actuelle
> documentée dans [`README.md`](../README.md) (racine) : `apps/rpi/main.py` +
> `config/features.yaml` + `config/rules.yaml`.

## Ce que c'est

Une génération précédente du projet (nom de code interne "Sim Env"), pilotée par un
fichier `config.json` (format JSON, pas YAML) au lieu de `config/features.yaml` +
`config/rules.yaml`. Elle n'est branchée ni sur le service systemd
(`deploy/steam-vision.service`), ni sur les scripts de lancement actuels
(`scripts/linux_run.sh`, `scripts/linux/install.sh`).

| Fichier | Rôle |
|---|---|
| `main.py` | Ancienne boucle principale ("S.T.E.A.M Vision v2"), modes `--debug`/`--escape`, lit `config.json` |
| `config.json` | Config JSON associée — **contenu obsolète** : plusieurs associations carte→vidéo/label sont incohérentes (ex. `plate_bois` déclenche la vidéo `cellule` avec le label de `plate_bougie`) |
| `gui_setup.py` | GUI Tkinter pour éditer `config.json` |
| `config_builder_app.py` | GUI Tkinter "Config Builder" — génère des dossiers de config exportables (`config.json` + `plaques/`) pour ce système |
| `example_configs/` | Exemples de configs pour `config_builder_app.py` (`mission_generic_yolo`, `mission_presence_only`) |
| `run_gui.bat`, `build_gui_exe.bat` | Lancent/compilent `gui.app` — **module `gui/` introuvable dans le dépôt**, ces scripts étaient déjà cassés avant l'archivage |
| `run_builder.bat`, `build_builder_exe.bat`, `build_all_exe.bat` | Lancent/compilent `config_builder_app.py` |
| `run.sh` | Ancien script de lancement Linux (`python3 -m gui.app`) — également cassé, même raison |

## Pourquoi archivé plutôt que supprimé

Conservé pour référence et traçabilité historique (git `mv`, pas de perte de code),
mais retiré de l'arbre actif pour éviter toute confusion avec la pipeline de
production réelle. Voir l'audit du 2026-07-18 pour le détail de l'investigation.
