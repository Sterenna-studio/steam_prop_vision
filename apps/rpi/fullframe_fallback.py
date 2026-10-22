"""
apps/rpi/fullframe_fallback.py
Politique du repli plein cadre quand L1 ne trouve plus de contour.

Un doigt sur le bord de la carte casse le quadrilatère de L1 (10 % de L1 hit
dans le pilote occlusion), alors que L2/L3 retrouvent la carte dans l'image
entière (86,7 % de triggers corrects contre 33,3 % pour le contour seul).
Mais chercher dans l'image entière coûte cher et augmente le risque de faux
positif ; cette politique le borne :
- seulement après `min_l1_misses` frames consécutives sans contour ;
- au plus une tentative toutes les `interval_s` secondes (coût plafonné) ;
- seulement si la scène a bougé récemment (`motion_ok`) : une salle vide et
  figée ne déclenche jamais de recherche plein cadre ;
- un résultat issu du repli doit dépasser le seuil de `score_margin`
  (plus strict que le chemin normal, plus fiable à contour détecté).

Pure (aucun OpenCV, aucune caméra) : testable hors Pi. Désactivée par défaut.
"""

from __future__ import annotations


class FullFrameFallback:
    def __init__(
        self,
        min_l1_misses: int = 3,
        interval_s: float = 0.7,
        score_margin: float = 0.05,
        motion_window_s: float = 5.0,
    ):
        self.min_l1_misses = max(1, int(min_l1_misses))
        self.interval_s = float(interval_s)
        self.score_margin = float(score_margin)
        self.motion_window_s = float(motion_window_s)
        self._misses = 0
        self._last_attempt = float("-inf")
        self.attempts = 0
        self.found = 0

    @classmethod
    def from_config(cls, cfg: dict) -> FullFrameFallback | None:
        """None si la fonctionnalité est désactivée (défaut)."""
        if not cfg.get("enable_fullframe_fallback", False):
            return None
        return cls(
            min_l1_misses=cfg.get("fullframe_min_l1_misses", 3),
            interval_s=cfg.get("fullframe_interval_s", 0.7),
            score_margin=cfg.get("fullframe_score_margin", 0.05),
            motion_window_s=cfg.get("fullframe_motion_window_s", 5.0),
        )

    def note_l1_hit(self) -> None:
        self._misses = 0

    def should_try(self, now: float, motion_ok: bool = True) -> bool:
        """À appeler à chaque frame où L1 échoue ; compte l'échec. True si
        une tentative plein cadre est autorisée maintenant (et l'enregistre)."""
        self._misses += 1
        if (
            self._misses < self.min_l1_misses
            or not motion_ok
            or now - self._last_attempt < self.interval_s
        ):
            return False
        self._last_attempt = now
        self.attempts += 1
        return True

    def between_attempts(self, now: float) -> bool:
        """Vrai si une tentative a eu lieu il y a moins de 2 intervalles : les
        frames sans contour qui suivent n'ont pas été évaluées, elles ne
        doivent pas compter comme des ratés. Au-delà (plus de tentative :
        scène figée, repli épuisé), elles comptent à nouveau, ce qui évite
        qu'un candidat périmé reste indéfiniment en attente."""
        return now - self._last_attempt <= 2 * self.interval_s

    def record_found(self) -> None:
        self.found += 1

    def accepts(self, score: float, threshold: float) -> bool:
        """Seuil plus strict pour un résultat obtenu par le repli."""
        return score >= threshold + self.score_margin
