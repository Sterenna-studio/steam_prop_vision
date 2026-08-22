"""Découverte et lecture déterministe du corpus image/vidéo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
import yaml

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


@dataclass
class CorpusMetadata:
    expected: str | None
    condition: str = "unspecified"
    severity: str | None = None
    notes: str = ""
    sequence_id: str | None = None
    fps: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class CorpusEntry:
    path: Path
    relative_path: str
    media_type: str
    metadata: CorpusMetadata


@dataclass
class CorpusFrame:
    entry: CorpusEntry
    image: np.ndarray
    frame_index: int
    timestamp_s: float


def discover_corpus(
    root: str | Path, object_id: str | None = None
) -> list[CorpusEntry]:
    corpus_root = Path(root)
    if not corpus_root.exists():
        raise FileNotFoundError(f"Corpus introuvable: {corpus_root}")
    entries = []
    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file() or path.name.lower() in {
            "readme.md",
            "metadata.yaml",
            "metadata.yml",
        }:
            continue
        extension = path.suffix.lower()
        if extension not in _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS:
            continue
        relative = path.relative_to(corpus_root)
        metadata = load_metadata(path, corpus_root)
        # Les négatifs restent inclus avec --object afin de mesurer les faux
        # positifs, au lieu de produire un recall isolé artificiellement flatteur.
        if object_id and metadata.expected not in {object_id, None}:
            continue
        entries.append(
            CorpusEntry(
                path=path,
                relative_path=relative.as_posix(),
                media_type="image" if extension in _IMAGE_EXTENSIONS else "video",
                metadata=metadata,
            )
        )
    return entries


def load_metadata(path: Path, corpus_root: Path) -> CorpusMetadata:
    inferred = _infer_metadata(path, corpus_root)
    values = {}
    sidecars = [path.with_suffix(".yaml"), path.with_suffix(".yml")]
    for sidecar in sidecars:
        if sidecar.exists():
            loaded = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"Metadata invalide (mapping attendu): {sidecar}")
            values = loaded
            break
    expected = values.pop("expected", inferred.expected)
    if isinstance(expected, str) and expected.lower() in {
        "none",
        "null",
        "negative",
        "negatives",
    }:
        expected = None
    return CorpusMetadata(
        expected=expected,
        condition=str(values.pop("condition", inferred.condition)),
        severity=values.pop("severity", None),
        notes=str(values.pop("notes", "")),
        sequence_id=values.pop("sequence_id", path.stem),
        fps=_optional_float(values.pop("fps", None)),
        extra=values,
    )


def iter_frames(entry: CorpusEntry) -> Iterator[CorpusFrame]:
    if entry.media_type == "image":
        image = cv2.imread(str(entry.path))
        if image is None:
            raise ValueError(f"Image illisible: {entry.path}")
        yield CorpusFrame(entry, image, 0, 0.0)
        return

    capture = cv2.VideoCapture(str(entry.path))
    if not capture.isOpened():
        raise ValueError(f"Vidéo illisible: {entry.path}")
    fps = entry.metadata.fps or capture.get(cv2.CAP_PROP_FPS) or 0.0
    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = index / fps if fps > 0 else 0.0
            yield CorpusFrame(entry, frame, index, timestamp)
            index += 1
    finally:
        capture.release()


def _infer_metadata(path: Path, corpus_root: Path) -> CorpusMetadata:
    relative = path.relative_to(corpus_root)
    parts = relative.parts
    expected = parts[0] if len(parts) > 1 else None
    if expected and expected.lower() in {"negative", "negatives"}:
        expected = None
    condition = parts[1] if len(parts) > 2 else "unspecified"
    return CorpusMetadata(expected=expected, condition=condition)


def _optional_float(value) -> float | None:
    return None if value is None else float(value)
