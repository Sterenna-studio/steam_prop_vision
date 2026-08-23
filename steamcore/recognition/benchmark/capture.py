"""Capture d'un corpus terrain depuis le flux MJPEG du runtime STYX."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from typing import BinaryIO, Iterator
from urllib.request import urlopen

import cv2
import numpy as np
import yaml


_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


@dataclass(frozen=True)
class CaptureOptions:
    corpus: Path
    object_id: str | None
    condition: str
    duration_s: float = 10.0
    fps: float = 2.0
    stream_url: str = "http://127.0.0.1:5050/stream"
    countdown_s: float = 3.0
    severity: str | None = None
    notes: str = ""
    timeout_s: float = 10.0
    source_orientation: str = "runtime-corrected"


@dataclass(frozen=True)
class CaptureResult:
    directory: Path
    sequence_id: str
    frames_saved: int
    elapsed_s: float


def capture_mjpeg_session(options: CaptureOptions) -> CaptureResult:
    """Capture une séquence échantillonnée et écrit un sidecar par image."""
    _validate_options(options)
    sequence_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    object_dir = options.object_id or "negatives"
    directory = options.corpus / object_dir / options.condition / sequence_id
    directory.mkdir(parents=True, exist_ok=False)

    if options.countdown_s:
        time.sleep(options.countdown_s)

    started = time.monotonic()
    deadline = started + options.duration_s
    next_sample = started
    frames_saved = 0
    interval = 1.0 / options.fps

    with urlopen(options.stream_url, timeout=options.timeout_s) as response:  # noqa: S310
        for jpeg in iter_mjpeg_jpegs(response):
            now = time.monotonic()
            if now >= deadline:
                break
            if now < next_sample:
                continue
            if not _is_decodable_jpeg(jpeg):
                continue

            stem = f"frame_{frames_saved:04d}"
            (directory / f"{stem}.jpg").write_bytes(jpeg)
            metadata = {
                "expected": options.object_id,
                "condition": options.condition,
                "severity": options.severity,
                "notes": options.notes,
                "sequence_id": sequence_id,
                "fps": options.fps,
                "source": options.stream_url,
                "camera": {"orientation": options.source_orientation},
            }
            (directory / f"{stem}.yaml").write_text(
                yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            frames_saved += 1
            next_sample = now + interval

    elapsed = time.monotonic() - started
    if frames_saved == 0:
        directory.rmdir()
        raise RuntimeError("Aucune image JPEG valide reçue depuis le flux MJPEG")
    return CaptureResult(directory, sequence_id, frames_saved, elapsed)


def iter_mjpeg_jpegs(stream: BinaryIO, chunk_size: int = 65536) -> Iterator[bytes]:
    """Extrait les images JPEG sans dépendre du backend vidéo d'OpenCV."""
    buffer = bytearray()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            return
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                if len(buffer) > chunk_size:
                    del buffer[:-2]
                break
            end = buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start:
                    del buffer[:start]
                break
            end += 2
            yield bytes(buffer[start:end])
            del buffer[:end]


def _is_decodable_jpeg(data: bytes) -> bool:
    encoded = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) is not None


def _validate_options(options: CaptureOptions) -> None:
    if options.object_id is not None and not _SAFE_NAME.fullmatch(options.object_id):
        raise ValueError("Identifiant objet invalide")
    if not _SAFE_NAME.fullmatch(options.condition):
        raise ValueError("Condition invalide")
    if options.duration_s <= 0:
        raise ValueError("La durée doit être strictement positive")
    if options.fps <= 0:
        raise ValueError("Le nombre d'images par seconde doit être positif")
    if options.countdown_s < 0:
        raise ValueError("Le compte à rebours ne peut pas être négatif")
    if options.source_orientation not in {"raw", "runtime-corrected"}:
        raise ValueError("Orientation source invalide")
