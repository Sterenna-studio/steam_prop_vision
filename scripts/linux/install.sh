#!/bin/bash
# scripts/linux/install.sh
# Installation complète + service systemd sur Raspberry Pi (Trixie / aarch64)
set -e

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SERVICE_SRC="$REPO_DIR/deploy/steam-vision.service"
SERVICE_DST="/etc/systemd/system/steam-vision.service"

echo "=== S.T.E.A.M Prop Vision — Install RPi ==="
echo "    Répertoire : $REPO_DIR"

# ── Dépendances système ────────────────────────────────────────────
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg mpv \
    python3-tk libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev

# ── Virtualenv + dépendances Python ───────────────────────────────
cd "$REPO_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements_rpi.txt

# ── Service systemd ────────────────────────────────────────────────
echo ""
echo "=== Installation du service systemd ==="
sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable steam-vision
echo "Service installé et activé au démarrage."

echo ""
echo "=== Installation terminée ==="
echo ""
echo "Commandes utiles :"
echo "  sudo systemctl start   steam-vision   # démarrer"
echo "  sudo systemctl stop    steam-vision   # arrêter"
echo "  sudo systemctl restart steam-vision   # relancer"
echo "  sudo systemctl status  steam-vision   # état"
echo "  journalctl -u steam-vision -f         # logs live"
echo ""
echo "Stream caméra (depuis le réseau) :"
echo "  http://$(hostname -I | awk '{print $1}'):5050/stream"
