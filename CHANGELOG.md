# Changelog — S.T.E.A.M Vision

## v2.0.0 — 17 mai 2026

### 🔴 Robustesse production
- `main.py` : `try/except` global + logging rotatif `logs/steam_vision.log`
- `main.py` : `boot_checks()` au démarrage — vérifie mpv, PLATEST, rules.yaml
- `deploy/steam-vision.service` : service systemd `Restart=on-failure`
- `deploy/INSTALL_SERVICE.md` : guide d'installation

### 🖼️ Plates PLATEST
- Ajout : `plate_bois`, `plate_bougie`, `plate_cellule`, `plate_chaudron`, `plate_dague`, `plate_vampire`

### ⚙️ Configs & scripts
- Mise à jour : `config/rules.yaml`, `config.json`, `run.sh`, `add_plate.sh`, `split_all_plates.sh`
- Ajout : `stream.py`, `test_cam.py`

### 📋 Documentation
- `AUDIT.md` : rapport d'audit complet mai 2026
