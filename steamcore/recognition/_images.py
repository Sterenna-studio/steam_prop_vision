"""
steamcore/recognition/_images.py
Découverte des images de template PLATEST/plate_xxx/ — partagé par
CardDetector (L2) et CardRecognizer (L3).
"""

from __future__ import annotations
from pathlib import Path

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def find_template_images(directory: Path) -> list[Path]:
    """Liste triée des images de template d'un dossier (récursif).

    Ignore les fichiers cachés et les planches-contact preview_*.jpg
    générées par tools/generate_samples.py.
    """
    return sorted(
        p
        for p in directory.rglob("*")
        if p.suffix.lower() in _IMAGE_EXTS
        and not p.name.startswith(".")
        and not p.name.startswith("preview_")
    )
