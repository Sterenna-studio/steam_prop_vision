"""
download_model.py
-----------------
Télécharge automatiquement le modèle YOLO requis par S.T.E.A.M Vision.

Usage :
    python download_model.py
    python download_model.py --model yolov8n.pt
    python download_model.py --model yolov8s.pt --dest models/

Le fichier est téléchargé depuis les serveurs Ultralytics et placé
dans le dossier courant (ou --dest) s'il n'existe pas déjà.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_MODEL = "yolov8n.pt"
DEFAULT_DEST  = Path(".")


def download(model: str = DEFAULT_MODEL, dest: Path = DEFAULT_DEST) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / model

    if target.exists():
        print(f"[download_model] ✅ {target} déjà présent, rien à faire.")
        return target

    print(f"[download_model] Téléchargement de {model} → {target} ...")
    try:
        from ultralytics.utils.downloads import safe_download
        url = f"https://github.com/ultralytics/assets/releases/download/v8.2.0/{model}"
        safe_download(url, file=target)
    except ImportError:
        # Fallback urllib si ultralytics non installé
        import urllib.request
        url = f"https://github.com/ultralytics/assets/releases/download/v8.2.0/{model}"
        print(f"[download_model] ultralytics non disponible, urllib fallback → {url}")
        urllib.request.urlretrieve(url, target)

    if target.exists():
        size_mb = target.stat().st_size / 1_048_576
        print(f"[download_model] ✅ {target} téléchargé ({size_mb:.1f} MB)")
    else:
        print(f"[download_model] ❌ Échec du téléchargement de {model}", file=sys.stderr)
        sys.exit(1)

    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Télécharge le modèle YOLO pour S.T.E.A.M Vision")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Nom du modèle (défaut: {DEFAULT_MODEL})")
    parser.add_argument("--dest",  default=str(DEFAULT_DEST), help="Dossier destination (défaut: .)")
    args = parser.parse_args()
    download(model=args.model, dest=Path(args.dest))


if __name__ == "__main__":
    main()
