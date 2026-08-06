"""
steamcore/recognition/template_registry.py
Cache partagé pour CardDetector (L2) et CardRecognizer (L3) : évite de lire
et décoder deux fois les mêmes images PLATEST au chargement.

Les descripteurs restent calculés séparément PAR EXTRACTEUR+CONFIG (ex.
"orb:600" pour CardDetector, "orb:800" pour CardRecognizer, "sift:800" si
SIFT activé en L2) — jamais mélangés entre backends ou nfeatures différents,
puisque les descripteurs ORB/SIFT ne sont comparables qu'entre eux-mêmes.
Seule l'image décodée (niveaux de gris, résolution native) est partagée ;
chaque appelant applique son propre resize avant detectAndCompute().
"""

from __future__ import annotations
from pathlib import Path
import cv2
import numpy as np

from ._images import find_template_images


class TemplateRegistry:
    def __init__(self, platest_dir: str = "PLATEST"):
        self.platest_dir = Path(platest_dir)
        self._image_cache: dict[Path, np.ndarray | None] = {}
        self._descriptor_cache: dict[str, dict[str, list]] = {}

    def _decode(self, path: Path) -> np.ndarray | None:
        """Lit et convertit une image en gris (résolution native), une seule
        fois par chemin quel que soit le nombre d'appelants."""
        if path not in self._image_cache:
            img = cv2.imread(str(path))
            self._image_cache[path] = (
                cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img is not None else None
            )
        return self._image_cache[path]

    def get_templates(
        self,
        feat,
        cache_key: str,
        resize: int | None = None,
        min_keypoints: int = 4,
    ) -> dict[str, list[tuple[str, object, np.ndarray, int, int]]]:
        """{card_id: [(nom_image, keypoints, descripteurs, hauteur, largeur), ...]}

        Calculé une seule fois par `cache_key`, puis réutilisé. `resize` et
        `min_keypoints` doivent rester cohérents pour un même cache_key —
        ce sont des propriétés de l'extracteur, pas des paramètres par appel.
        """
        if cache_key in self._descriptor_cache:
            return self._descriptor_cache[cache_key]

        by_card: dict[str, list] = {}
        if self.platest_dir.exists():
            for subdir in sorted(self.platest_dir.iterdir()):
                if not subdir.is_dir():
                    continue
                imgs = find_template_images(subdir)
                if not imgs:
                    continue
                entries = []
                for p in imgs:
                    gray = self._decode(p)
                    if gray is None:
                        continue
                    h, w = gray.shape[:2]
                    if resize:
                        gray = cv2.resize(gray, (resize, resize))
                    kps, desc = feat.detectAndCompute(gray, None)
                    if desc is not None and len(kps) >= min_keypoints:
                        entries.append((p.name, kps, desc, h, w))
                if entries:
                    by_card[subdir.name] = entries

        self._descriptor_cache[cache_key] = by_card
        return by_card

    def invalidate(self) -> None:
        """Vide les caches (images + descripteurs) — à appeler avant un
        reload() pour que les nouveaux fichiers PLATEST soient repris."""
        self._image_cache.clear()
        self._descriptor_cache.clear()
