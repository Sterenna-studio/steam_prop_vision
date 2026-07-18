# Stratégie de dépendances — pérennité ~10 ans

> Objectif : que ce dépôt reste installable et fonctionnel sur STYX (ou une machine
> de remplacement identique) même des années après la dernière intervention active,
> sans qu'un `pip install` finisse par tirer une version majeure incompatible.

## Cible matérielle/logicielle validée

| Composant | Version |
|---|---|
| Machine | Raspberry Pi 5 (STYX) |
| Caméra | IMX708 (nappe CSI) |
| OS | Debian Trixie (aarch64) |
| Python | 3.13 |
| Lecteur vidéo | `mpv` (fallback `ffplay`/`vlc`) |
| Audio | `aplay` (fallback `mpg123`) |

## Bornage des dépendances (`requirements_rpi.txt` / `requirements.txt`)

Les planchers (`>=`) existants datent du démarrage du projet et n'étaient plus
bornés vers le haut : un `pip install` refait dans plusieurs années pourrait
silencieusement installer une version majeure incompatible (ex. OpenCV 5.x, sorti
en 2026, change potentiellement des APIs utilisées ici). Chaque dépendance a donc
reçu une borne haute excluant la prochaine version majeure connue :

```
picamera2>=0.3.19,<0.4
opencv-python-headless>=4.8,<5.0
ultralytics>=8.0,<9.0
numpy>=1.26,<2.0
PyYAML>=6.0,<7.0
websockets>=12.0,<17.0
```

`numpy<2.0` est volontaire : ultralytics/opencv de cette génération ont été
qualifiés avec la ligne 1.26.x. Un passage à numpy 2.x est possible mais doit être
testé explicitement (changements ABI) avant de relever la borne.

`picamera2` reste néanmoins piloté par **`apt`/le système** sur STYX (venv créé
avec `--system-site-packages`, voir [`SETUP_VENV.md`](SETUP_VENV.md)) — la version
pip n'est qu'indicative ; c'est la version fournie par Debian qui fait foi.

## Ce qui manque encore pour un figeage complet (`==`)

Ces bornes `>=,<` protègent contre une rupture majeure mais **ne garantissent pas
la reproductibilité exacte**. Pour un figeage complet et validé sur le matériel
réel :

1. Sur STYX, après une installation qui passe la validation fonctionnelle complète
   (voir l'issue de mise en production) :
   ```bash
   pip freeze > requirements_rpi.lock.txt
   apt list --installed 2>/dev/null | grep -iE "picamera2|libcamera" >> requirements_rpi.lock.txt
   git add requirements_rpi.lock.txt
   ```
2. Committer ce fichier comme référence figée de restauration — c'est lui (pas
   `requirements_rpi.txt`) qui doit être utilisé pour recréer une machine
   identique dans le futur.
3. Idéalement, archiver aussi les wheels téléchargées (`pip download -r
   requirements_rpi.lock.txt -d wheelhouse/`) sur un support hors-ligne, au cas où
   PyPI ne proposerait plus ces versions précises dans 10 ans.

Cette étape n'a pas pu être faite depuis ce poste de dev (pas d'accès à STYX ni au
matériel Pi 5 + IMX708) — elle nécessite une session sur la machine réelle.
