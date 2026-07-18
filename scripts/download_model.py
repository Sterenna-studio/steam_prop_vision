"""
scripts/download_model.py
Télécharge yolov8n.pt si absent (via ultralytics hub).
Usage : python scripts/download_model.py [--model yolov8n.pt]
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

DEFAULT_MODEL = "yolov8n.pt"
ROOT = Path(__file__).resolve().parent.parent


def download(model_name: str = DEFAULT_MODEL) -> Path:
    dest = ROOT / model_name
    if dest.exists():
        print(
            f"[model] {dest.name} déjà présent ({dest.stat().st_size // 1024} Ko) — skip."
        )
        return dest

    print(f"[model] Téléchargement de {model_name} ...")
    try:
        from ultralytics import YOLO

        YOLO(model_name)  # ultralytics télécharge dans ~/.ultralytics puis copie
        # Chercher le fichier téléchargé dans les chemins standards
        import ultralytics

        ul_root = Path(ultralytics.__file__).parent
        candidates = list(ul_root.rglob(model_name)) + list(
            (Path.home() / ".ultralytics").rglob(model_name)
        )
        if candidates:
            import shutil

            shutil.copy2(candidates[0], dest)
            print(f"[model] Copié → {dest}")
        else:
            # ultralytics peut aussi déposer le fichier dans le cwd
            cwd_file = Path(model_name)
            if cwd_file.exists():
                import shutil

                shutil.move(str(cwd_file), dest)
                print(f"[model] Déplacé → {dest}")
            else:
                print(
                    "[model] ⚠️  Fichier non trouvé après téléchargement. Vérifier manuellement."
                )
                sys.exit(1)
    except ImportError:
        print("[model] ❌  ultralytics non installé. Lancer : pip install ultralytics")
        sys.exit(1)
    except Exception as e:
        print(f"[model] ❌  Erreur téléchargement : {e}")
        sys.exit(1)

    print(f"[model] ✅  {dest.name} prêt ({dest.stat().st_size // 1024} Ko)")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Télécharge le modèle YOLO si absent")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help="Nom du modèle (ex: yolov8n.pt)"
    )
    args = parser.parse_args()
    download(args.model)
