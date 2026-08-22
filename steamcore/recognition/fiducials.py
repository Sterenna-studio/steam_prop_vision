"""Backends ArUco/AprilTag OpenCV produisant des PerceptionResult."""

from __future__ import annotations

from pathlib import Path
import time

import cv2
import numpy as np

from steamcore.perception import PerceptionResult


class FiducialUnavailableError(RuntimeError):
    pass


class OpenCVFiducialBackend:
    def __init__(
        self,
        family: str = "DICT_4X4_50",
        id_mapping: dict[int, str] | None = None,
        backend_name: str = "aruco",
    ):
        aruco = _aruco_module()
        if not hasattr(aruco, family):
            raise ValueError(f"Dictionnaire/famille OpenCV inconnu: {family}")
        self.name = backend_name
        self.family = family
        self.id_mapping = id_mapping or {}
        self.dictionary = aruco.getPredefinedDictionary(getattr(aruco, family))
        self._detector = (
            aruco.ArucoDetector(self.dictionary)
            if hasattr(aruco, "ArucoDetector")
            else None
        )

    def detect(self, frame: np.ndarray) -> list[PerceptionResult]:
        aruco = _aruco_module()
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self._detector is not None:
            corners, ids, rejected = self._detector.detectMarkers(gray)
        else:
            corners, ids, rejected = aruco.detectMarkers(gray, self.dictionary)
        if ids is None:
            return []
        results = []
        for marker_corners, marker_id in zip(corners, ids.reshape(-1)):
            points = marker_corners.reshape(4, 2).astype(np.float32)
            x, y, width, height = cv2.boundingRect(points)
            numeric_id = int(marker_id)
            results.append(
                PerceptionResult(
                    id=self.id_mapping.get(numeric_id, str(numeric_id)),
                    confidence=1.0,
                    backend=self.name,
                    timestamp=time.time(),
                    corners=points,
                    bbox=(float(x), float(y), float(width), float(height)),
                    metadata={
                        "marker_id": numeric_id,
                        "family": self.family,
                        "rejected_candidates": len(rejected),
                        "confidence_source": "decoded_marker",
                    },
                )
            )
        return results

    def generate(self, marker_id: int, side_pixels: int = 512) -> np.ndarray:
        aruco = _aruco_module()
        if hasattr(aruco, "generateImageMarker"):
            return aruco.generateImageMarker(self.dictionary, marker_id, side_pixels)
        image = np.zeros((side_pixels, side_pixels), dtype=np.uint8)
        aruco.drawMarker(self.dictionary, marker_id, side_pixels, image, 1)
        return image

    def export_png(
        self, marker_id: int, path: str | Path, side_pixels: int = 1024
    ) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output), self.generate(marker_id, side_pixels)):
            raise OSError(f"Impossible d'écrire {output}")
        return output

    def export_svg(
        self,
        marker_id: int,
        path: str | Path,
        size_mm: float = 80.0,
        margin_mm: float = 8.0,
    ) -> Path:
        marker_size = int(self.dictionary.markerSize) + 2
        marker = self.generate(marker_id, marker_size)
        total = size_mm + 2 * margin_mm
        cells = []
        cell_size = size_mm / marker_size
        for row in range(marker_size):
            for column in range(marker_size):
                if marker[row, column] < 128:
                    cells.append(
                        f'<rect x="{margin_mm + column * cell_size:.6f}" '
                        f'y="{margin_mm + row * cell_size:.6f}" '
                        f'width="{cell_size:.6f}" height="{cell_size:.6f}"/>'
                    )
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}mm" '
            f'height="{total}mm" viewBox="0 0 {total} {total}">\n'
            f'<rect width="{total}" height="{total}" fill="white"/>\n'
            '<g fill="black">\n' + "\n".join(cells) + "\n</g>\n</svg>\n"
        )
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(svg, encoding="utf-8")
        return output


def create_aruco_backend(
    dictionary: str = "DICT_4X4_50", id_mapping: dict[int, str] | None = None
) -> OpenCVFiducialBackend:
    return OpenCVFiducialBackend(dictionary, id_mapping, "aruco")


def create_apriltag_backend(
    family: str = "DICT_APRILTAG_36h11", id_mapping: dict[int, str] | None = None
) -> OpenCVFiducialBackend:
    return OpenCVFiducialBackend(family, id_mapping, "apriltag")


def fiducials_available() -> bool:
    return hasattr(cv2, "aruco")


def _aruco_module():
    if not fiducials_available():
        raise FiducialUnavailableError(
            "cv2.aruco est absent; installer une build OpenCV contrib compatible"
        )
    return cv2.aruco
