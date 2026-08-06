"""
apps/rpi/qr_flux.py
Validation de flux/mission via QR code, montré par le GM avant le lancement
d'une session. Format attendu : "STEAM_FLUX:<mission_id>" (ex: STEAM_FLUX:flux_1).
Comparé à cfg["mission_id"] — lecture seule, ne modifie jamais la config active.

Décodage : pyzbar/ZBar en priorité (pip install pyzbar + apt install libzbar0).
cv2.QRCodeDetector (natif, sans dépendance) est utilisé en repli, mais s'est
montré peu fiable en pratique : il échoue de façon reproductible sur certains
QR pourtant valides (ex. contenu se terminant par un chiffre impair dans nos
tests) — voir DEPENDENCIES.md. À n'utiliser que si pyzbar/libzbar0 ne peuvent
pas être installés.
"""

from __future__ import annotations
import logging

import cv2

try:
    from pyzbar.pyzbar import decode as _zbar_decode

    QR_BACKEND = "zbar"
except ImportError:
    _zbar_decode = None
    QR_BACKEND = "cv2"

log = logging.getLogger("steam")

QR_FLUX_PREFIX = "STEAM_FLUX:"
QR_CHECK_EVERY = 5  # ne scanne le QR qu'une frame sur N (coût CPU)
QR_REPEAT_COOLDOWN = 3.0  # s avant de repousser le même event pour le même QR


def _decode_qr(frame, cv2_detector) -> str | None:
    """Décode un QR dans la frame (pyzbar si dispo, sinon cv2 en repli)."""
    if _zbar_decode is not None:
        results = _zbar_decode(frame)
        return results[0].data.decode("utf-8", errors="ignore") if results else None
    data, _, _ = cv2_detector.detectAndDecode(frame)
    return data or None


class QRFluxChecker:
    """Scan QR de validation de flux/mission (1 frame sur QR_CHECK_EVERY).

    Lecture seule : compare le flux scanné à mission_id, ne modifie jamais la
    config active. check() retourne l'event à pousser sur le monitor WS
    (system_ready / flux_mismatch), ou None si rien à signaler.
    """

    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._cv2_detector = cv2.QRCodeDetector()  # utilisé si pyzbar absent
        self._last_payload: str | None = None
        self._last_time = 0.0
        log.info(f"[qr] Backend décodage : {QR_BACKEND}")
        if QR_BACKEND != "zbar":
            log.warning(
                "[qr] pyzbar/libzbar0 absent — repli sur cv2.QRCodeDetector, "
                "moins fiable (voir DEPENDENCIES.md). "
                "Installer : sudo apt install libzbar0 && pip install pyzbar"
            )

    def check(self, frame, frame_count: int, now: float) -> dict | None:
        if frame_count % QR_CHECK_EVERY != 0:
            return None
        data = _decode_qr(frame, self._cv2_detector)
        if not data or not data.startswith(QR_FLUX_PREFIX):
            return None

        flux_id = data[len(QR_FLUX_PREFIX) :]
        repeat = (
            flux_id == self._last_payload
            and (now - self._last_time) < QR_REPEAT_COOLDOWN
        )
        if repeat:
            return None
        self._last_payload = flux_id
        self._last_time = now

        if flux_id == self.mission_id:
            log.info(f"[qr] Flux valide : {flux_id}")
            return {
                "type": "system_ready",
                "label": f"STEAM VISION READY — {flux_id.upper()}",
            }
        log.warning(
            f"[qr] Flux inattendu : scanné={flux_id!r} attendu={self.mission_id!r}"
        )
        return {
            "type": "flux_mismatch",
            "expected": self.mission_id,
            "scanned": flux_id,
        }
