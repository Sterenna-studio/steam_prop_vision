"""
apps/rpi/boot.py
Vérifications au démarrage : dépendances critiques + nettoyage des processus
orphelins d'un crash précédent.
"""

from __future__ import annotations
import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("steam")


def _kill_orphan_players() -> None:
    """Tue les mpv/ffplay orphelins d'un crash précédent (best-effort).

    Un crash brutal du process principal (SIGKILL, freeze -> watchdog) laisse
    le sous-processus mpv/ffplay tourner indépendamment (reparenté à init) :
    sans ce nettoyage, il continue d'afficher/boucler par-dessus la nouvelle
    instance qui redémarre.
    """
    if not shutil.which("pkill"):
        return
    for name in ("mpv", "ffplay"):
        try:
            subprocess.run(
                ["pkill", "-x", name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.warning(f"[boot] pkill {name} : {e}")


def boot_checks() -> None:
    """Vérifie les dépendances critiques au démarrage. Abort si manquant."""
    _kill_orphan_players()
    errors = []

    # Lecteur vidéo
    players = ["mpv", "ffplay", "vlc"]
    if not any(shutil.which(p) for p in players):
        errors.append(
            "Aucun lecteur vidéo trouvé (mpv / ffplay / vlc). "
            "Installer avec : sudo apt install mpv"
        )
    else:
        found = next(p for p in players if shutil.which(p))
        log.info(f"[boot] Lecteur vidéo : {found} OK")

    # aplay pour l'audio
    if not shutil.which("aplay") and not shutil.which("mpg123"):
        log.warning("[boot] WARN : aplay et mpg123 introuvables — audio désactivé")

    # PLATEST
    if not Path("PLATEST").exists() or not any(Path("PLATEST").iterdir()):
        errors.append("Dossier PLATEST vide ou absent — aucun template de plate.")
    else:
        plates = [d for d in Path("PLATEST").iterdir() if d.is_dir()]
        log.info(f"[boot] PLATEST : {len(plates)} plate(s) trouvée(s)")

    # config/rules.yaml
    if not Path("config/rules.yaml").exists():
        log.warning(
            "[boot] WARN : config/rules.yaml absent — aucune action ne sera déclenchée"
        )

    if errors:
        for e in errors:
            log.error(f"[boot] ERREUR CRITIQUE : {e}")
        log.error("[boot] Démarrage annulé.")
        sys.exit(1)
